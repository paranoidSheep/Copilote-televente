"""Mise à l'écart des données inexploitables et diagnostic des données (règles, contrat, API, CLI)."""

from __future__ import annotations

import json
from datetime import date, timedelta

import pytest
from fastapi.testclient import TestClient

from copilote.analyses import MotifEcart, Referentiel, filtrer_exploitables
from copilote.api import creer_app
from copilote.application import creer_application
from copilote.comptes import DepotUtilisateursMemoire
from copilote.config import Config, ConfigDatahub, ConfigSecurite, ModeLLM
from copilote.datahub import SourceEnCache, sans_cache
from copilote.datahub.http import HttpDataSource
from copilote.datahub.mock import MockDataSource
from copilote.diagnostic import (
    DonneesBrutes,
    Gravite,
    StatutDiagnostic,
    Traitement,
    controler_qualite,
    diagnostiquer,
)
from copilote.diagnostic.__main__ import formater, main
from copilote.diagnostic.rapport import statut_global
from copilote.domaine import Client, Commande, ErreurConfiguration, ErreurSourceDonnees, Famille, Lot
from copilote.journal import DepotMemoire
from copilote.services import ServiceDiagnostic

from .conftest import AUJOURD_HUI, JETON_SIMULATEUR, SECRET_TEST, client, commande, lot, produit

PERIODE = 183


def source_http(url: str, jeton: str = JETON_SIMULATEUR) -> HttpDataSource:
    return HttpDataSource(ConfigDatahub(url=url, token=jeton, date_reference=AUJOURD_HUI))


def brutes(**donnees: object) -> DonneesBrutes:
    """Petit jeu de données sain, que chaque test abîme à sa façon."""
    base: dict[str, object] = {
        "clients": (client("R1"), client("R2")),
        "produits": (produit("P1"), produit("P2"), produit("S1", famille=Famille.SURGELE, duree_vie=0)),
        "commandes": (
            *(commande(f"A{i}", "R1", 7 * i, [("P1", 5)]) for i in range(1, 7)),
            commande("B1", "R2", 3, [("P2", 1)]),
        ),
        "lots": (lot("L1", "P1", 10, 5),),
    }
    base.update(donnees)
    return DonneesBrutes(date_du_jour=AUJOURD_HUI, **base)  # type: ignore[arg-type]


def compte(donnees: DonneesBrutes) -> dict[str, int]:
    return {r.code: r.nombre for r in controler_qualite(donnees) if r.nombre}


# --------------------------------------------------------------------------- mise à l'écart


def test_filtrage_des_donnees_inexploitables():
    clients = [client("R1"), client("R1"), client("R2")]
    produits = [produit("P1"), produit("P1"), produit("P2")]
    commandes = [
        commande("C1", "R1", 3, [("P1", 2), ("ZZ", 1)]),  # une ligne orpheline : la commande est gardée
        commande("C1", "R1", 3, [("P1", 2)]),  # doublon
        commande("C2", "R1", 4, [("ZZ", 1)]),  # plus aucune ligne exploitable
        commande("C3", "INCONNU", 5, [("P1", 1)]),
        commande("C4", "R2", -2, [("P2", 1)]),  # dans le futur
        commande("C5", "R2", 6, [("P2", 1)]),
    ]
    lots = [lot("L1", "P1", 5, 3), lot("L2", "ZZ", 5, 3), lot("L3", "P2", 5, -1), lot("L4", "P2", 5, 0)]

    donnees = filtrer_exploitables(AUJOURD_HUI, clients, produits, commandes, lots)

    assert list(donnees.clients) == ["R1", "R2"] and list(donnees.produits) == ["P1", "P2"]
    assert [c.id for c in donnees.commandes] == ["C5", "C1"]  # triées par date
    assert [ligne.produit_code for ligne in donnees.commandes[1].lignes] == ["P1"]
    assert [l.id for l in donnees.lots] == ["L1", "L4"]  # L4 expire aujourd'hui : encore en stock
    assert sorted((e.motif.value, e.identifiant) for e in donnees.ecarts) == sorted(
        [
            (MotifEcart.CLIENT_DUPLIQUE, "R1"),
            (MotifEcart.PRODUIT_DUPLIQUE, "P1"),
            (MotifEcart.LIGNE_PRODUIT_INCONNU, "C1"),
            (MotifEcart.COMMANDE_DUPLIQUEE, "C1"),
            (MotifEcart.LIGNE_PRODUIT_INCONNU, "C2"),
            (MotifEcart.COMMANDE_CLIENT_INCONNU, "C3"),
            (MotifEcart.COMMANDE_FUTURE, "C4"),
            (MotifEcart.LOT_PRODUIT_INCONNU, "L2"),
            (MotifEcart.LOT_PERIME, "L3"),
        ]
    )


def test_donnees_saines_rien_n_est_ecarte(ref_mock: Referentiel):
    assert ref_mock.ecarts == ()


def test_le_copilote_reste_utilisable_sur_des_donnees_defectueuses(url_simulateur_anomalies: str, horloge):
    """Avant la mise à l'écart, le plan d'écoulement échouait sur la commande d'un client inconnu."""
    app = creer_application(
        Config(mode_llm=ModeLLM.REPLI, securite=ConfigSecurite(secret_session=SECRET_TEST)),
        source=source_http(url_simulateur_anomalies),
        depot_journal=DepotMemoire(),
        horloge=horloge,
        depot_utilisateurs=DepotUtilisateursMemoire(),
    )
    ref = app.referentiels.obtenir()
    assert len(ref.ecarts) == 8 and len(ref.clients) == 30
    plan = app.pilotage.plan_ecoulement()
    assert "L-PERIME" not in {ligne.situation.lot_id for ligne in plan.lignes}  # jamais de lot périmé proposé
    assert len(app.pilotage.file_appels().appels) == 30
    assert "" not in app.pilotage.televendeurs()  # le client sans télévendeur n'ajoute pas de file vide
    for client_id in ("C001", "C006", ref.commandes[-1].client_id):
        assert app.fiches.generer(client_id).client.id == client_id


# --------------------------------------------------------------------------- règles de qualité


def test_jeu_sain_aucune_anomalie():
    assert compte(brutes()) == {}


def test_jeu_complet_du_mock_conforme(mock_source: MockDataSource):
    rapport = diagnostiquer(mock_source, PERIODE)
    assert rapport.statut is StatutDiagnostic.CONFORME
    assert rapport.enregistrements_ecartes == 0 and all(v.reussie for v in rapport.contrat)
    assert rapport.volumes is not None and rapport.volumes.clients == 30


@pytest.mark.parametrize(
    ("modification", "attendu"),
    [
        ({"clients": (client("R1"), client("R2"), client("R1"))}, {"client_duplique": 1}),
        ({"produits": (produit("P1"), produit("P2"), produit("P2"))}, {"produit_duplique": 1}),
        ({"lots": (lot("L1", "P1", 10, 5), lot("L9", "ZZ", 1, 5))}, {"lot_produit_inconnu": 1}),
        ({"lots": (lot("L1", "P1", 10, -3),)}, {"lot_perime": 1}),
        ({"produits": (produit("P1", prix=0), produit("P2"))}, {"prix_nul": 1}),
        ({"produits": (produit("P1", duree_vie=0), produit("P2"))}, {"duree_vie_nulle": 1}),
        ({"clients": (client("R1"), client("R2", commercial=" "))}, {"client_sans_televendeur": 1}),
        ({"clients": (client("R1"), client("R2"), client("R3"))}, {"client_sans_commande": 1}),
        (
            {"clients": (client("R1"), client("R2").model_copy(update={"telephone": ""}))},
            {"client_sans_telephone": 1},
        ),
    ],
)
def test_chaque_regle_detecte_son_anomalie(modification: dict[str, object], attendu: dict[str, int]):
    assert compte(brutes(**modification)) == attendu


def test_regles_sur_les_commandes():
    saines = brutes().commandes
    futur = commande("F1", "R1", -5, [("P1", 1)])
    inconnu = commande("X1", "R9", 2, [("P1", 1)])
    orpheline = commande("O1", "R1", 2, [("P1", 1), ("ZZ", 1)])
    enorme = commande("Q1", "R1", 1, [("P1", 500)])  # 100 fois la quantité habituelle
    resultat = compte(brutes(commandes=(*saines, saines[0], futur, inconnu, orpheline, enorme)))
    assert resultat == {
        "commande_dupliquee": 1,
        "commande_future": 1,
        "commande_client_inconnu": 1,
        "ligne_produit_inconnu": 1,
        "quantite_aberrante": 1,
    }


def test_quantite_aberrante_seulement_avec_assez_d_historique():
    commandes = (commande("A1", "R1", 7, [("P1", 5)]), commande("A2", "R1", 1, [("P1", 500)]))
    assert "quantite_aberrante" not in compte(brutes(commandes=commandes))


def test_lot_recu_apres_sa_dlc():
    incoherent = Lot(
        id="L7",
        produit_code="P1",
        quantite=3,
        dlc=AUJOURD_HUI + timedelta(days=2),
        date_reception=AUJOURD_HUI + timedelta(days=4),
        entrepot="Test",
    )
    assert compte(brutes(lots=(incoherent,))) == {"lot_recu_apres_dlc": 1}


def test_exemples_limites_et_regles_documentees():
    clients = tuple(client(f"R{i}") for i in range(1, 30))
    resultat = {r.code: r for r in controler_qualite(brutes(clients=clients))}
    assert resultat["client_sans_commande"].nombre == 27
    assert len(resultat["client_sans_commande"].exemples) == 8
    assert all(r.impact and r.libelle for r in resultat.values())
    ecartees = {r.code for r in resultat.values() if r.traitement is Traitement.ECARTE}
    assert ecartees == {m.value for m in MotifEcart}  # chaque écart des analyses a sa règle


# --------------------------------------------------------------------------- contrat et connexion


class SourceDefaillante(MockDataSource):
    """Datahub qui ignore ses filtres et répond n'importe quoi à un identifiant inconnu."""

    def get_client(self, client_id: str) -> Client:
        return self.get_clients()[1]

    def get_order_history(self, client_id: str | None = None, depuis: date | None = None) -> list[Commande]:
        return [commande("ANCIENNE", "C001", 300, [("FR001", 1)]), *super().get_order_history()]

    def get_stock(self) -> list[Lot]:
        return []


class SourceSansLignes(MockDataSource):
    def get_order_history(self, client_id: str | None = None, depuis: date | None = None) -> list[Commande]:
        return [c.model_copy(update={"lignes": ()}) for c in super().get_order_history(client_id, depuis)]


class SourceEnPanne(MockDataSource):
    def get_products(self) -> list:  # type: ignore[type-arg]
        raise ErreurSourceDonnees("délai dépassé")


def test_contrat_non_respecte():
    rapport = diagnostiquer(SourceDefaillante(), PERIODE)
    verdicts = {v.libelle: v for v in rapport.contrat}
    assert not verdicts["Lecture d'un client par son identifiant"].reussie
    assert not verdicts["Client inexistant signalé comme introuvable (404)"].reussie
    assert not verdicts["Filtre des commandes par client (client_id)"].reussie
    assert not verdicts["Filtre des commandes par date (depuis)"].reussie
    assert verdicts["Lignes de commande incluses dans l'historique"].reussie
    assert rapport.statut is StatutDiagnostic.A_CORRIGER
    assert "5 points du contrat non respectés" not in rapport.resume and "4 points du contrat" in rapport.resume


def test_commandes_sans_lignes():
    rapport = diagnostiquer(SourceSansLignes(), PERIODE)
    verdict = next(v for v in rapport.contrat if v.libelle.startswith("Lignes"))
    assert not verdict.reussie and "commandes sans aucune ligne" in verdict.detail


def test_source_en_panne():
    rapport = diagnostiquer(SourceEnPanne(), PERIODE)
    assert rapport.statut is StatutDiagnostic.LECTURE_IMPOSSIBLE
    assert rapport.volumes is None and rapport.qualite == () and rapport.contrat == ()
    en_erreur = [m for m in rapport.connexion if m.erreur]
    assert [m.ressource for m in en_erreur] == ["produits"] and en_erreur[0].volume is None
    assert rapport.resume == "Lecture des données impossible. Catalogue produits : délai dépassé"


def test_statut_global():
    rapport = diagnostiquer(MockDataSource(), PERIODE)
    alerte = rapport.qualite[-3].model_copy(update={"nombre": 1})  # client_sans_televendeur
    critique = rapport.qualite[0].model_copy(update={"nombre": 1})
    assert alerte.gravite is Gravite.ALERTE and critique.gravite is Gravite.CRITIQUE
    assert statut_global(rapport.connexion, rapport.contrat, (alerte,)) is StatutDiagnostic.A_SURVEILLER
    assert statut_global(rapport.connexion, rapport.contrat, (alerte, critique)) is StatutDiagnostic.A_CORRIGER


def test_diagnostic_du_simulateur_avec_anomalies(url_simulateur_anomalies: str):
    rapport = diagnostiquer(source_http(url_simulateur_anomalies), PERIODE)
    assert rapport.source == "http" and rapport.statut is StatutDiagnostic.A_CORRIGER
    assert all(v.reussie for v in rapport.contrat), rapport.contrat
    assert [m.volume for m in rapport.connexion] == [31, 81, 1315, 139]
    assert {r.code: r.nombre for r in rapport.qualite if r.nombre} == {
        "client_duplique": 1,
        "produit_duplique": 1,
        "commande_dupliquee": 1,
        "commande_client_inconnu": 1,
        "ligne_produit_inconnu": 1,
        "lot_produit_inconnu": 1,
        "commande_future": 1,
        "lot_perime": 1,
        "prix_nul": 1,
        "duree_vie_nulle": 1,
        "lot_recu_apres_dlc": 1,
        "quantite_aberrante": 1,
        "client_sans_televendeur": 1,
        "client_sans_telephone": 1,
    }
    assert rapport.enregistrements_ecartes == 8
    assert rapport.resume.endswith("6 contrôles critiques, 7 alertes. 8 enregistrements écartés des analyses.")


def test_diagnostic_jeton_refuse(url_simulateur: str):
    rapport = diagnostiquer(source_http(url_simulateur, jeton="faux"), PERIODE)
    assert rapport.statut is StatutDiagnostic.LECTURE_IMPOSSIBLE
    assert "DATAHUB_TOKEN" in rapport.resume and "et 3 autres ressources en erreur" in rapport.resume


def test_service_mesure_la_source_sans_le_cache(mock_source: MockDataSource):
    en_cache = SourceEnCache(mock_source, 300)
    assert sans_cache(en_cache) is mock_source and sans_cache(mock_source) is mock_source
    instants = iter(range(100))
    service = ServiceDiagnostic(en_cache, Referentiel.charger(mock_source).regles, chrono=lambda: next(instants) / 10)
    rapport = service.executer()
    assert all(m.duree_ms == 100 for m in rapport.connexion)  # chaque lecture : un « tic » de 100 ms


# --------------------------------------------------------------------------- API et ligne de commande


def test_api_diagnostic_reserve_aux_responsables(api, api_televendeur, application):
    reponse = api.get("/admin/diagnostic")
    assert reponse.status_code == 200
    assert reponse.json()["statut"] == "conforme" and len(reponse.json()["qualite"]) == 15
    assert api_televendeur.get("/admin/diagnostic").status_code == 403
    assert TestClient(creer_app(application)).get("/admin/diagnostic").status_code == 401


def test_ligne_de_commande(monkeypatch, capsys, url_simulateur: str, url_simulateur_anomalies: str):
    monkeypatch.setenv("DATASOURCE", "mock")
    assert main([]) == 0
    assert "Statut : CONFORME" in capsys.readouterr().out

    monkeypatch.setenv("DATASOURCE", "http")
    monkeypatch.setenv("DATAHUB_TOKEN", JETON_SIMULATEUR)
    monkeypatch.setenv("DATAHUB_DATE_REFERENCE", AUJOURD_HUI.isoformat())
    monkeypatch.setenv("DATAHUB_URL", url_simulateur_anomalies)
    assert main(["--json"]) == 1
    assert json.loads(capsys.readouterr().out)["statut"] == "a_corriger"

    monkeypatch.setenv("DATAHUB_TOKEN", "faux")
    assert main([]) == 2
    assert "LECTURE IMPOSSIBLE" in capsys.readouterr().out


def test_rapport_texte(url_simulateur_anomalies: str):
    texte = formater(diagnostiquer(source_http(url_simulateur_anomalies), PERIODE))
    assert "Statut : À CORRIGER" in texte
    assert "✓ Filtre des commandes par client (client_id)" in texte
    assert "[critique] Commande d'un client inconnu : 1 (écarté des analyses)" in texte
    assert "CMD-CLIENT-INCONNU — client C999 absent du référentiel clients" in texte
    assert "(1/15 règles sans anomalie)" in texte


def test_date_de_reference_invalide():
    with pytest.raises(ErreurConfiguration):
        Config.depuis_environnement({"DATAHUB_DATE_REFERENCE": "23/10/2026"})
