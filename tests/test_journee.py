"""La journée du télévendeur : apprentissage des retours, agenda des rappels, objectifs, tournée, export CSV."""

from __future__ import annotations

import csv
import io
from datetime import date, datetime, timedelta

import pytest

from copilote.agent import creer_boite_outils
from copilote.agent.llm import AppelOutil
from copilote.analyses import (
    Referentiel,
    StatutRappel,
    analyser_stock_client,
    analyser_suggestions,
    apprendre,
    avancement_tournee,
    construire_agenda,
    construire_file_appels,
    objectifs_du_jour,
)
from copilote.application import Application, creer_application
from copilote.config import Config, ConfigSecurite, ModeLLM
from copilote.evaluation import DepotEvaluationsMemoire
from copilote.journal import CompteRendu, DepotMemoire, Issue, NouveauCompteRendu, Origine, Reponse, commandes_csv
from tests.test_services import ligne

from .conftest import AUJOURD_HUI, SECRET_TEST, client_connecte

MATIN = datetime.combine(AUJOURD_HUI, datetime.min.time()).replace(hour=9)


def cr(
    client_id: str,
    jours_avant: int = 0,
    lignes=(),
    *,
    issue: Issue = Issue.PAS_DE_BESOIN,
    rappel: date | None = None,
    televendeur: str = "Julie Moreau",
    identifiant: int = 1,
) -> CompteRendu:
    return CompteRendu(
        id=identifiant,
        client_id=client_id,
        televendeur=televendeur,
        issue=issue,
        rappel_le=rappel,
        lignes=list(lignes),
        cree_le=MATIN - timedelta(days=jours_avant),
    )


def retours_restaurants() -> list[CompteRendu]:
    """Restaurants (C002, C003, C005) : l'emmental FR008 toujours refusé, SG023 et FR014 toujours acceptés."""
    comptes_rendus = []
    for i, client_id in enumerate(["C002", "C003", "C005", "C002", "C003"]):
        comptes_rendus.append(
            cr(
                client_id,
                jours_avant=10 + i,
                lignes=[
                    ligne("FR008", Reponse.REFUSE),
                    ligne("SG023", Reponse.ACCEPTE),
                    ligne("FR014", Reponse.ACCEPTE, Origine.SUGGESTION),
                    ligne("FR031", Reponse.REFUSE, Origine.SUGGESTION),
                    ligne("FR001", Reponse.REFUSE, Origine.MANQUANT),  # un habituel n'est pas une offre : ignoré
                    ligne("SG006", Reponse.SANS_REPONSE),  # sans réponse : ignoré
                ],
            )
        )
    return comptes_rendus


# --------------------------------------------------------------------------- apprentissage


def test_apprentissage_compte_les_offres_par_produit_et_type(ref_mock: Referentiel):
    modele = apprendre(retours_restaurants(), ref_mock.clients, AUJOURD_HUI)
    assert (modele.global_.acceptes, modele.global_.proposes) == (10, 20)
    assert set(modele.par_produit_et_type) == {
        ("FR008", "Restaurant"),
        ("SG023", "Restaurant"),
        ("FR014", "Restaurant"),
        ("FR031", "Restaurant"),
    }
    refuse = modele.retour("FR008", "Restaurant")
    assert refuse is not None and refuse.sens == -1 and refuse.taux_acceptation_pct == 0
    assert refuse.justification == "Accepté 0 fois sur 5 par des établissements « Restaurant » : proposé en dernier"
    assert modele.retour("SG023", "Restaurant").sens == 1  # type: ignore[union-attr]
    assert modele.retour("SG023", "EHPAD") is None  # aucun retour d'EHPAD


def test_apprentissage_prudent(ref_mock: Referentiel):
    """Moins de 3 propositions, ou trop anciennes : aucune conclusion. Écart faible : neutre."""
    peu = [cr("C002", 5, [ligne("FR008", Reponse.REFUSE)]), cr("C003", 5, [ligne("FR008", Reponse.REFUSE)])]
    assert apprendre(peu, ref_mock.clients, AUJOURD_HUI).retour("FR008", "Restaurant") is None
    anciens = [cr("C002", 120, [ligne("FR008", Reponse.REFUSE)])] * 5
    assert apprendre(anciens, ref_mock.clients, AUJOURD_HUI).vide
    inconnu = [cr("C999", 1, [ligne("FR008", Reponse.REFUSE)])] * 5
    assert apprendre(inconnu, ref_mock.clients, AUJOURD_HUI).vide
    equilibre = [cr("C002", 1, [ligne("FR008", r)]) for r in [Reponse.ACCEPTE, Reponse.REFUSE] * 3]
    retour = apprendre(equilibre, ref_mock.clients, AUJOURD_HUI).retour("FR008", "Restaurant")
    assert retour is not None and retour.sens == 0 and retour.justification.endswith("dans la moyenne")


def test_apprentissage_module_le_classement_du_stock(ref_mock: Referentiel):
    modele = apprendre(retours_restaurants(), ref_mock.clients, AUJOURD_HUI)
    avant = [p.code for p in analyser_stock_client(ref_mock, "C001").produits]
    apres = analyser_stock_client(ref_mock, "C001", acceptation=modele).produits
    assert avant == ["FR008", "FR004", "SG006", "SG023", "FR016", "FR021"]
    # SG023 souvent accepté passe devant ; FR008 souvent refusé recule d'une demi-marche seulement :
    # il reste devant les produits seulement « déjà achetés » (FR016, FR021).
    assert [p.code for p in apres] == ["SG023", "FR004", "SG006", "FR008", "FR016", "FR021"]
    assert apres[0].retour_clients is not None and apres[0].retour_clients.sens == 1


def test_apprentissage_module_les_suggestions(ref_mock: Referentiel):
    modele = apprendre(retours_restaurants(), ref_mock.clients, AUJOURD_HUI)
    # FR031 et FR014 sont adoptés par 75 % des restaurants : à égalité, l'ordre alphabétique départage.
    assert [s.code for s in analyser_suggestions(ref_mock, "C001").produits] == ["FR031", "FR014", "SG007"]
    apres = analyser_suggestions(ref_mock, "C001", acceptation=modele).produits
    assert [s.code for s in apres] == ["FR014", "FR031", "SG007"]  # FR014 accepté, FR031 refusé
    assert apres[1].retour_clients is not None and apres[1].retour_clients.sens == -1


@pytest.fixture
def application_journal(mock_source, horloge, depot_utilisateurs) -> tuple[Application, DepotMemoire]:
    depot = DepotMemoire()
    application = creer_application(
        Config(mode_llm=ModeLLM.SIMULE, securite=ConfigSecurite(secret_session=SECRET_TEST)),
        source=mock_source,
        depot_journal=depot,
        horloge=horloge,
        depot_utilisateurs=depot_utilisateurs,
        depot_evaluations=DepotEvaluationsMemoire(),
    )
    return application, depot


def enregistrer(depot: DepotMemoire, compte_rendu: CompteRendu) -> None:
    depot.enregistrer(NouveauCompteRendu(**compte_rendu.model_dump(exclude={"id", "cree_le"})), compte_rendu.cree_le)


def test_la_fiche_et_l_ia_profitent_de_l_apprentissage(application_journal):
    application, depot = application_journal
    for compte_rendu in retours_restaurants():
        enregistrer(depot, compte_rendu)
    production = application.fiches.produire("C001", ModeLLM.REPLI)
    assert production.contexte.stock.produits[0].code == "SG023"
    assert production.fiche.stock_a_ecouler[0].retour_clients is not None
    ref = application.referentiels.obtenir()
    boite = creer_boite_outils(ref, "C001", [], application.fiches.apprentissage())
    sortie = boite.executer(AppelOutil(id="1", nom="stock_a_ecouler", arguments={"client_id": "C001"}))
    assert '"retour_clients"' in sortie.contenu and "proposé en dernier" in sortie.contenu


# --------------------------------------------------------------------------- agenda, objectifs, tournée


def test_agenda_des_rappels(ref_mock: Referentiel):
    comptes_rendus = [
        cr("C003", 5, issue=Issue.RAPPELER, rappel=AUJOURD_HUI - timedelta(days=2)),  # en retard
        cr("C006", 3, issue=Issue.RAPPELER, rappel=AUJOURD_HUI),  # aujourd'hui
        cr("C012", 1, issue=Issue.RAPPELER, rappel=AUJOURD_HUI + timedelta(days=4)),  # à venir
        cr("C014", 6, issue=Issue.RAPPELER, rappel=AUJOURD_HUI),  # traité depuis :
        cr("C014", 1),  # un appel plus récent a eu lieu
    ]
    agenda = construire_agenda(ref_mock, comptes_rendus)
    assert [e.client.id for e in agenda.en_retard] == ["C003"] and agenda.en_retard[0].ecart_jours == -2
    assert [e.client.id for e in agenda.aujourdhui] == ["C006"]
    assert [(e.client.id, e.statut) for e in agenda.a_venir] == [("C012", StatutRappel.A_VENIR)]
    commercial = ref_mock.client("C003").commercial
    filtre = construire_agenda(ref_mock, comptes_rendus, commercial)
    assert all(e.client.commercial == commercial for e in filtre.en_retard + filtre.aujourdhui + filtre.a_venir)


def test_objectifs_du_jour(ref_mock: Referentiel):
    commande = [ligne("FR008", Reponse.ACCEPTE)]  # 4 × 9,90 € × (1 - 20 %) = 31,68 €
    comptes_rendus = [
        cr("C001", 0, commande, issue=Issue.COMMANDE),
        cr("C002", 0),
        cr("C003", 0, commande, issue=Issue.COMMANDE, televendeur="Karim Bensaïd"),
        cr("C004", 1, commande, issue=Issue.COMMANDE),  # hier : non compté
    ]
    julie = objectifs_du_jour(comptes_rendus, AUJOURD_HUI, ref_mock.regles, "Julie Moreau")
    assert (julie.appels.realise, julie.appels.cible, julie.appels.pct) == (2, 20, 10)
    assert julie.ca_accepte_ht.realise == 31.68 and julie.commandes == 1 and julie.taux_transformation_pct == 50
    equipe = objectifs_du_jour(comptes_rendus, AUJOURD_HUI, ref_mock.regles, None, nb_televendeurs=3)
    assert (equipe.appels.realise, equipe.appels.cible, equipe.ca_accepte_ht.cible) == (3, 60, 4500.0)
    rien = objectifs_du_jour([], AUJOURD_HUI, ref_mock.regles, "Julie Moreau")
    assert rien.taux_transformation_pct is None and rien.appels.pct == 0


def test_avancement_de_la_tournee(ref_mock: Referentiel):
    file = construire_file_appels(ref_mock, [], "Julie Moreau")
    tournee = avancement_tournee(file)
    assert tournee.faits == 0 and tournee.total == len(file.appels) > 3
    assert [e.score for e in tournee.etapes] == sorted((e.score for e in tournee.etapes), reverse=True)
    premier = tournee.etapes[0].client_id
    assert tournee.prochain is not None and tournee.prochain.client.id == premier
    apres = avancement_tournee(construire_file_appels(ref_mock, [cr(premier, 0)], "Julie Moreau"))
    assert apres.faits == 1 and apres.etapes[0].fait and apres.prochain is not None
    assert apres.prochain.client.id == tournee.etapes[1].client_id
    tout = [cr(e.client_id, 0) for e in tournee.etapes]
    fin = avancement_tournee(construire_file_appels(ref_mock, tout, "Julie Moreau"))
    assert fin.faits == fin.total and fin.prochain is None


def test_api_journee(application_journal):
    application, depot = application_journal
    enregistrer(depot, cr("C006", 2, issue=Issue.RAPPELER, rappel=AUJOURD_HUI))
    julie = client_connecte(application, "julie")
    journee = julie.get("/appels/journee", params={"televendeur": "Karim Bensaïd"}).json()
    assert journee["televendeur"] == "Julie Moreau"  # un télévendeur ne voit que sa journée
    assert journee["objectifs"]["appels"]["cible"] == 20
    assert [e["client"]["id"] for e in journee["agenda"]["aujourdhui"]] == ["C006"]
    premier = journee["tournee"]["prochain"]["client"]["id"]
    saisie = {"client_id": premier, "issue": "pas_de_besoin", "lignes": []}
    assert julie.post("/comptes-rendus", json=saisie).status_code == 201
    apres = julie.get("/appels/journee").json()
    assert apres["tournee"]["faits"] == 1 and apres["tournee"]["prochain"]["client"]["id"] != premier
    assert apres["objectifs"]["appels"]["realise"] == 1

    responsable = client_connecte(application, "resp").get("/appels/journee").json()
    assert responsable["televendeur"] is None and responsable["objectifs"]["appels"]["cible"] == 60


# --------------------------------------------------------------------------- export CSV


def test_export_csv_pour_excel():
    comptes_rendus = [
        cr(
            "C002",
            0,
            [ligne("FR008", Reponse.ACCEPTE), ligne("SG006", Reponse.REFUSE)],
            issue=Issue.COMMANDE,
            identifiant=7,
        ),
        cr("C001", 0, [ligne("=HYPERLIEN()", Reponse.ACCEPTE)], issue=Issue.COMMANDE, identifiant=3),
    ]
    contenu = commandes_csv(comptes_rendus, {"C001": "Le Bouchon", "C002": "La Table"})
    assert contenu.startswith("﻿Date;Heure;Télévendeur;")
    lignes = list(csv.reader(io.StringIO(contenu.removeprefix("﻿")), delimiter=";"))
    assert len(lignes) == 3  # en-tête + 2 produits acceptés (le refus n'est pas exporté)
    assert lignes[1][5] == "'=HYPERLIEN()"  # injection de formule neutralisée
    assert lignes[2][3:8] == ["C002", "La Table", "FR008", "FR008", "4"]
    assert lignes[2][9:13] == ["9,90", "20", "7,92", "31,68"]  # virgule décimale


def test_api_export_csv(application_journal):
    application, depot = application_journal
    enregistrer(depot, cr("C001", 0, [ligne("FR008", Reponse.ACCEPTE)], issue=Issue.COMMANDE))
    enregistrer(
        depot, cr("C002", 0, [ligne("FR001", Reponse.ACCEPTE)], issue=Issue.COMMANDE, televendeur="Karim Bensaïd")
    )
    enregistrer(depot, cr("C003", 1, [ligne("FR004", Reponse.ACCEPTE)], issue=Issue.COMMANDE))  # hier

    reponse = client_connecte(application, "julie").get("/comptes-rendus/commandes.csv?televendeur=Karim Bensaïd")
    assert reponse.status_code == 200 and reponse.headers["content-type"].startswith("text/csv")
    assert reponse.headers["content-disposition"] == 'attachment; filename="commandes-2026-10-23.csv"'
    assert [l.split(";")[5] for l in reponse.text.splitlines()[1:]] == ["FR008"]  # ses propres commandes du jour

    responsable = client_connecte(application, "resp")
    tout = responsable.get("/comptes-rendus/commandes.csv").text.splitlines()[1:]
    assert sorted(l.split(";")[5] for l in tout) == ["FR001", "FR008"]
    hier = responsable.get("/comptes-rendus/commandes.csv", params={"jour": "2026-10-22"}).text.splitlines()[1:]
    assert [l.split(";")[5] for l in hier] == ["FR004"]
