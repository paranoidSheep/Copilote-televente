"""Banc d'évaluation de la qualité des fiches : critères, synthèse, historique, service, API, ligne de commande."""

from __future__ import annotations

import json
import threading
from datetime import date, datetime, timedelta
from pathlib import Path

import pytest

from copilote.analyses import construire_contexte
from copilote.application import Application
from copilote.config import ModeLLM
from copilote.domaine import ClientIntrouvable
from copilote.evaluation import (
    CampagneIntrouvable,
    DepotEvaluationsMemoire,
    DepotEvaluationsSQLite,
    EtatEvaluation,
    TypeSignal,
    en_markdown,
    evaluer_fiche,
    synthetiser,
)
from copilote.evaluation.criteres import nombre_de_phrases
from copilote.evaluation.synthese import percentile
from copilote.evaluation.tarifs import cout_usd
from copilote.fiche import Fiche, ModeFiche, TypeCorrection, assembler_fiche
from copilote.journal import DepotSQLite, Issue, NouveauCompteRendu, Reponse
from copilote.services import ErreurValidation, EvaluationEnCours
from scripts import evaluer
from tests.test_analyses import compte_rendu
from tests.test_fiche import MAINTENANT, redaction
from tests.test_services import ligne

from .conftest import AUJOURD_HUI

# --------------------------------------------------------------------------- critères


def fiche_r1(ref_simple, comptes_rendus=(), mode: ModeFiche = ModeFiche.IA, **champs) -> tuple[Fiche, object]:
    """Fiche du restaurant R1 (contact « M. Test ») à partir d'une rédaction donnée."""
    contexte = construire_contexte(ref_simple, "R1", list(comptes_rendus))
    base = {
        "resume_habitudes": "Restaurant fidèle. Il commande chaque vendredi.",
        "produits_manquants": [{"code": "P2", "commentaire": "À relancer"}],
        "stock_a_ecouler": [{"code": "P1", "remise_pct": 30, "argument": "DLC demain"}],
        "accroches": ["Bonjour M. Test, je vous remets du P2 ?", "Le P1 à -30 % : je vous en mets ?"],
    }
    fiche = assembler_fiche(contexte, redaction(**{**base, **champs}), mode=mode, genere_le=MAINTENANT, modele="test")
    return fiche, contexte


def test_fiche_irreprochable(ref_simple):
    fiche, contexte = fiche_r1(ref_simple)
    note = evaluer_fiche(fiche, contexte, ModeLLM.ANTHROPIC, duree_ms=1200)
    assert (note.score_global, note.score_fidelite, note.score_couverture, note.score_format) == (100, 100, 100, 100)
    assert [s.type for s in note.signaux] == [TypeSignal.MANQUANT_PRIORITAIRE, TypeSignal.LOT_URGENT_HABITUEL]
    assert not note.repli_force and note.cout_usd is None  # pas de trace : ni jetons ni coût


def test_corrections_et_remise_annoncee_penalisent_la_fidelite(ref_simple):
    fiche, contexte = fiche_r1(
        ref_simple,
        produits_manquants=[{"code": "INVENTE", "commentaire": "x"}, {"code": "P2", "commentaire": "À relancer"}],
        stock_a_ecouler=[{"code": "P1", "remise_pct": 80, "argument": "Prix cassé à -50 %"}],
        resume_habitudes="Activité en baisse (-37 % sur 3 mois). Commande le vendredi.",
    )
    note = evaluer_fiche(fiche, contexte, ModeLLM.ANTHROPIC, duree_ms=1)
    types = {c.type for c in note.corrections}
    assert types == {TypeCorrection.PRODUIT_INCONNU, TypeCorrection.REMISE_PLAFONNEE}
    assert note.remises_hors_regle == ("« -50 % » cité, aucune remise de 50 % proposée",)  # la tendance est ignorée
    assert note.score_fidelite == 100 - 25 - 20 - 20


def test_signaux_repris_par_le_redacteur_et_non_par_les_garde_fous(ref_simple):
    rappel = compte_rendu("R1", 1, Issue.RAPPELER, rappel=AUJOURD_HUI + timedelta(days=1))
    invente = {"code": "INVENTE", "remise_pct": 5, "argument": "x"}
    fiche, contexte = fiche_r1(ref_simple, [rappel], produits_manquants=[], stock_a_ecouler=[invente])
    note = evaluer_fiche(fiche, contexte, ModeLLM.ANTHROPIC, duree_ms=1)
    assert {c.type for c in note.corrections} >= {TypeCorrection.STOCK_COMPLETE, TypeCorrection.RAPPEL_AJOUTE}
    assert "P1" in {s.code for s in fiche.stock_a_ecouler}  # ajouté par le garde-fou…
    assert [(s.type, s.couvert) for s in note.signaux] == [
        (TypeSignal.MANQUANT_PRIORITAIRE, False),
        (TypeSignal.LOT_URGENT_HABITUEL, False),  # … donc non compté au crédit du rédacteur
        (TypeSignal.RAPPEL_PROMIS, False),
    ]
    assert note.score_couverture == 0


def test_controles_de_format(ref_simple):
    fiche, contexte = fiche_r1(
        ref_simple,
        resume_habitudes="Un seul bloc sans fin de phrase",
        accroches=["Salut, tu prends du P2 ?", "x" * 230],
        stock_a_ecouler=[{"code": "P1", "remise_pct": 30, "argument": " "}],
    )
    controles = {c.libelle: c for c in evaluer_fiche(fiche, contexte, ModeLLM.SIMULE, duree_ms=1).controles_format}
    assert not controles["Contact cité dans une accroche"].reussi
    assert controles["Accroches de 220 caractères au plus"].detail == "accroche 2 : 230 caractères"
    assert controles["Vouvoiement"].detail == "« tu »"
    assert controles["Résumé des habitudes en 2 ou 3 phrases"].detail == "1 phrase"
    assert controles["Chaque proposition est argumentée"].detail == "P1 sans argument"


def test_nombre_de_phrases_ignore_les_abreviations():
    assert nombre_de_phrases("M. Lambert commande le lundi. Mme Roux aussi !") == 2
    assert nombre_de_phrases("") == 0


def test_tarifs():
    assert cout_usd("claude-sonnet-5-5", 1_000_000, 100_000) == pytest.approx(3.0)
    assert cout_usd("claude-sonnet-5-5 (simulé)", 1000, 0) == pytest.approx(0.002)  # tarif du modèle imité
    assert cout_usd("modele-inconnu", 1000, 1000) is None and cout_usd(None, 1, 1) is None


def test_synthese(ref_simple):
    fiche, contexte = fiche_r1(ref_simple)
    mauvaise, _ = fiche_r1(ref_simple, accroches=["Tu veux du P1 ?", "Ok"])
    notes = [evaluer_fiche(f, contexte, ModeLLM.SIMULE, duree_ms=d) for f, d in ((fiche, 100), (mauvaise, 300))]
    s = synthetiser(ModeLLM.SIMULE, notes)
    assert s.nb_fiches == 2 and s.fiches_sans_defaut == 1
    assert s.latence_mediane_ms == 200 and s.latence_p95_ms == 300
    assert {d.libelle for d in s.defauts_format} == {"Contact cité dans une accroche", "Vouvoiement"}
    assert s.cout_total_usd is None and not s.cout_projete
    assert percentile([], 0.95) == 0 and percentile([5, 1, 3], 0.5) == 3
    with pytest.raises(ValueError):
        synthetiser(ModeLLM.SIMULE, [])


# --------------------------------------------------------------------------- service


def test_campagne_complete_sur_le_jeu_fictif(application: Application):
    campagne = application.evaluation.executer([ModeLLM.SIMULE, ModeLLM.REPLI], ["C001", "C007", "C012"])
    assert campagne.id == 1 and len(campagne.fiches) == 6
    assert [s.redacteur for s in campagne.syntheses] == [ModeLLM.SIMULE, ModeLLM.REPLI]
    simule, repli = campagne.syntheses
    assert repli.score_global == 100 and repli.cout_par_fiche_usd is None
    assert simule.cout_projete and simule.cout_par_fiche_usd is not None and simule.jetons_entree_moyens > 1000
    assert simule.signaux_couverts < simule.signaux_total  # l'IA simulée oublie le lot d'emmental à J+1
    assert len(campagne.empreinte_prompt) == 12 and campagne.source == "mock"
    assert application.evaluation.lister()[0].nb_clients == 3
    assert application.evaluation.obtenir(1) == campagne
    assert "| IA simulée · claude-sonnet-5-5 (simulé) |" in en_markdown(campagne)


def test_campagne_hors_cache_et_empreinte_stable(application: Application, monkeypatch):
    servie = application.fiches.generer("C001")
    premiere = application.evaluation.executer([ModeLLM.SIMULE], ["C001"], enregistrer=False)
    assert application.fiches.generer("C001") is servie  # les fiches des télévendeurs ne changent pas
    assert premiere.id is None and application.evaluation.lister() == []
    seconde = application.evaluation.executer([ModeLLM.SIMULE], ["C001"], enregistrer=False)
    assert seconde.empreinte_prompt == premiere.empreinte_prompt
    monkeypatch.setattr("copilote.services.evaluation.SYSTEME", "Nouvelle version du prompt")
    assert application.evaluation.executer([ModeLLM.SIMULE], ["C001"]).empreinte_prompt != premiere.empreinte_prompt


def test_demandes_invalides(application: Application):
    with pytest.raises(ErreurValidation, match="anthropic"):
        application.evaluation.executer([ModeLLM.ANTHROPIC])  # aucune clé : Claude indisponible
    with pytest.raises(ErreurValidation):
        application.evaluation.executer([])
    with pytest.raises(ClientIntrouvable):
        application.evaluation.executer([ModeLLM.REPLI], ["C999"])


def test_execution_en_arriere_plan(application: Application, monkeypatch):
    service = application.evaluation
    feu_vert = threading.Event()
    produire = application.fiches.produire

    def produire_lentement(client_id, mode=None):
        feu_vert.wait(5)
        return produire(client_id, mode)

    monkeypatch.setattr(application.fiches, "produire", produire_lentement)
    suivi = service.lancer([ModeLLM.REPLI], ["C001", "C002"])
    assert suivi.etat is EtatEvaluation.EN_COURS and suivi.total == 2
    with pytest.raises(EvaluationEnCours):
        service.lancer([ModeLLM.REPLI])
    feu_vert.set()
    service.attendre()
    fin = service.suivi()
    assert fin is not None and fin.etat is EtatEvaluation.TERMINEE and fin.faites == 2 and fin.campagne_id == 1


def test_echec_en_arriere_plan_restitue(application: Application, monkeypatch):
    def en_panne(client_id, mode=None):
        raise RuntimeError("panne du rédacteur")

    monkeypatch.setattr(application.fiches, "produire", en_panne)
    application.evaluation.lancer([ModeLLM.REPLI], ["C001"])
    application.evaluation.attendre()
    suivi = application.evaluation.suivi()
    assert suivi is not None and suivi.etat is EtatEvaluation.ECHOUEE and suivi.erreur == "panne du rédacteur"


# --------------------------------------------------------------------------- historique


def test_historique_sqlite(tmp_path: Path, application: Application):
    campagne = application.evaluation.executer([ModeLLM.REPLI], ["C001"], enregistrer=False)
    chemin = tmp_path / "evaluations.sqlite3"
    depot = DepotEvaluationsSQLite(chemin)
    assert depot.lister() == [] and not chemin.exists()  # créé à la première écriture seulement
    with pytest.raises(CampagneIntrouvable):
        depot.obtenir(1)
    premiere, seconde = depot.enregistrer(campagne), depot.enregistrer(campagne)
    assert (premiere.id, seconde.id) == (1, 2)
    relu = DepotEvaluationsSQLite(chemin)  # nouvelle instance : persistance réelle
    assert relu.obtenir(1) == premiere
    assert [r.id for r in relu.lister()] == [2, 1]
    with pytest.raises(CampagneIntrouvable):
        relu.obtenir(3)


def test_historique_memoire():
    depot = DepotEvaluationsMemoire()
    with pytest.raises(CampagneIntrouvable):
        depot.obtenir(1)


# --------------------------------------------------------------------------- API


def test_api_banc_d_evaluation(api, application: Application):
    reponse = api.post("/labo/evaluations", json={"redacteurs": ["simule", "repli"], "clients": ["C001", "C002"]})
    assert reponse.status_code == 202 and reponse.json()["total"] == 4
    application.evaluation.attendre()
    suivi = api.get("/labo/evaluations/suivi").json()
    assert suivi["etat"] == "terminee"
    historique = api.get("/labo/evaluations").json()
    assert [c["id"] for c in historique] == [suivi["campagne_id"]]
    detail = api.get(f"/labo/evaluations/{suivi['campagne_id']}").json()
    assert len(detail["fiches"]) == 4 and detail["syntheses"][0]["redacteur"] == "simule"
    rapport = api.get(f"/labo/evaluations/{suivi['campagne_id']}/rapport.md")
    assert rapport.headers["content-type"].startswith("text/markdown") and "# Évaluation" in rapport.text
    assert api.get("/labo/evaluations/99").status_code == 404


def test_api_banc_droits_et_validation(api, api_televendeur):
    assert api_televendeur.get("/labo/evaluations").status_code == 403
    assert api_televendeur.post("/labo/evaluations", json={"redacteurs": ["repli"]}).status_code == 403
    assert api.post("/labo/evaluations", json={"redacteurs": []}).status_code == 422
    assert api.post("/labo/evaluations", json={"redacteurs": ["anthropic"]}).status_code == 422
    assert api.post("/labo/evaluations", json={"redacteurs": ["repli"], "clients": ["C999"]}).status_code == 404
    assert api.get("/labo/evaluations/suivi").json() is None


def test_api_une_seule_campagne_a_la_fois(api, application: Application, monkeypatch):
    feu_vert = threading.Event()
    produire = application.fiches.produire
    monkeypatch.setattr(application.fiches, "produire", lambda c, m=None: (feu_vert.wait(5), produire(c, m))[1])
    assert api.post("/labo/evaluations", json={"redacteurs": ["repli"], "clients": ["C001"]}).status_code == 202
    assert api.post("/labo/evaluations", json={"redacteurs": ["repli"]}).status_code == 409
    feu_vert.set()
    application.evaluation.attendre()


def test_comparaison_du_labo_hors_cache(api, application: Application):
    servie = application.fiches.generer("C003")
    assert set(api.get("/labo/clients/C003/comparaison").json()) == {"simule", "repli"}
    assert application.fiches.generer("C003") is servie
    assert api.get("/labo/clients/C999/comparaison").status_code == 404


# --------------------------------------------------------------------------- ligne de commande


def test_ligne_de_commande(tmp_path: Path, monkeypatch, capsys):
    monkeypatch.setenv("DOSSIER_DONNEES", str(tmp_path))
    monkeypatch.setenv("LLM_MODE", "simule")
    arguments = ["--redacteurs", "simule,repli", "--clients", "C001,C012", "--sortie", str(tmp_path / "rapports")]
    assert evaluer.main([*arguments, "--score-minimum", "50"]) == 0
    sortie = capsys.readouterr().out
    assert "IA simulée" in sortie and "Repli (sans IA)" in sortie
    rapports = sorted((tmp_path / "rapports").iterdir())
    assert [r.suffix for r in rapports] == [".json", ".md"]
    assert len(json.loads(rapports[0].read_text(encoding="utf-8"))["fiches"]) == 4
    assert DepotEvaluationsSQLite(tmp_path / "evaluations.sqlite3").lister()[0].nb_clients == 2

    assert evaluer.main([*arguments, "--score-minimum", "99", "--sans-historique"]) == 1  # IA simulée sous 99
    assert "ÉCHEC : IA simulée" in capsys.readouterr().out
    assert len(DepotEvaluationsSQLite(tmp_path / "evaluations.sqlite3").lister()) == 1


def test_repli_salue_toujours_le_contact(application: Application):
    """Défaut révélé par le banc : sans produit manquant, le repli ne nommait pas l'interlocuteur."""
    for client_id in ("C013", "C014", "C018"):
        fiche = application.fiches.produire(client_id, ModeLLM.REPLI).fiche
        nom = fiche.client.contact.split()[-1]
        assert fiche.accroches[0].startswith(f"Bonjour {fiche.client.contact}, ") and nom in fiche.accroches[0]


def test_dates_coherentes(application: Application):
    campagne = application.evaluation.executer([ModeLLM.REPLI], ["C001"], enregistrer=False)
    assert campagne.date_donnees == date(2026, 10, 23) and isinstance(campagne.lancee_le, datetime)


def test_ligne_de_commande_isolee_ignore_le_journal(tmp_path: Path, monkeypatch):
    """--isole : conditions de référence, quel que soit le contenu du journal local (contrôle de la CI)."""
    monkeypatch.setenv("DOSSIER_DONNEES", str(tmp_path))
    monkeypatch.setenv("LLM_MODE", "simule")
    lignes = [ligne("SG014", Reponse.REFUSE)]
    refus = NouveauCompteRendu(client_id="C019", televendeur="Julie", issue=Issue.PAS_DE_BESOIN, lignes=lignes)
    DepotSQLite(tmp_path / "journal.sqlite3").enregistrer(refus, datetime(2026, 10, 22, 9))
    arguments = ["--redacteurs", "simule", "--clients", "C019", "--sortie", str(tmp_path / "rapports")]

    assert evaluer.main([*arguments, "--score-minimum", "90"]) == 1  # le refus pénalise l'IA simulée
    assert evaluer.main([*arguments, "--isole", "--score-minimum", "90"]) == 0  # journal ignoré
    assert len(DepotEvaluationsSQLite(tmp_path / "evaluations.sqlite3").lister()) == 1  # --isole n'enregistre rien
