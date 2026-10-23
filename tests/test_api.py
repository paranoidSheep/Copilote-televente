"""API HTTP : codes de retour, contrats de réponse, traduction des erreurs, interface web."""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from copilote.api import creer_app
from scripts.generer_types_ts import SORTIE, generer


@pytest.fixture
def api(application) -> TestClient:
    return TestClient(creer_app(application))


def test_page_et_ressources_statiques(api):
    assert "Copilote télévente" in api.get("/").text
    assert api.get("/static/css/app.css").status_code == 200
    assert api.get("/static/js/main.js").status_code == 200


def test_sante(api):
    corps = api.get("/sante").json()
    assert corps["source_donnees"] == "mock" and corps["mode_par_defaut"] == "simule"
    assert {m["mode"] for m in corps["modes_disponibles"]} == {"simule", "repli"}
    assert len(corps["televendeurs"]) == 3


def test_clients_et_filtres(api):
    assert len(api.get("/clients").json()) == 30
    assert {c["type"] for c in api.get("/clients", params={"type": "EHPAD"}).json()} == {"EHPAD"}
    assert [c["id"] for c in api.get("/clients", params={"q": "momo"}).json()] == ["C010"]


def test_vue_360(api):
    corps = api.get("/clients/C010").json()
    assert corps["client"]["nom"] == "Pizza Momo" and corps["habitudes"]["nb_commandes"] > 0


def test_fiche(api):
    fiche = api.get("/clients/C005/fiche").json()
    assert fiche["mode"] == "ia_simulee"
    assert fiche["trace"]["etapes"] and fiche["panier"]["lignes"]
    assert api.get("/clients/C005/fiche", params={"mode": "repli"}).json()["mode"] == "repli"
    assert api.get("/clients/C005/fiche.txt").text.startswith("FICHE D'APPEL — Chez Lucette")
    assert api.get("/clients/C005/fiche", params={"mode": "inconnu"}).status_code == 422


def test_details_produit(api):
    assert api.get("/clients/C010/produits/FR007").json()["produit"]["code"] == "FR007"


@pytest.mark.parametrize(
    "url", ["/clients/C999", "/clients/C999/fiche", "/clients/C010/produits/XX", "/comptes-rendus/99/saisie-erp"]
)
def test_ressources_introuvables(api, url):
    reponse = api.get(url)
    assert reponse.status_code == 404 and "detail" in reponse.json()


def test_cycle_compte_rendu(api):
    nouveau = {
        "client_id": "C010",
        "televendeur": "Julie Moreau",
        "issue": "commande",
        "mode_fiche": "ia_simulee",
        "lignes": [
            {
                "code": "FR007",
                "libelle": "Mozzarella",
                "unite": "kg",
                "origine": "stock",
                "reponse": "accepte",
                "quantite": 5,
                "prix_unitaire_ht": 9.9,
                "remise_pct": 20,
            }
        ],
    }
    reponse = api.post("/comptes-rendus", json=nouveau)
    assert reponse.status_code == 201
    corps = reponse.json()
    assert "COMMANDE À SAISIR" in corps["texte_saisie_erp"]
    identifiant = corps["compte_rendu"]["id"]
    assert "FR007" in api.get(f"/comptes-rendus/{identifiant}/saisie-erp").text
    assert len(api.get("/comptes-rendus", params={"client_id": "C010"}).json()) == 1
    assert api.get("/statistiques", params={"jours": 7}).json()["nb_appels"] == 1


def test_compte_rendu_invalide(api):
    rappel_sans_date = {"client_id": "C010", "televendeur": "J", "issue": "rappeler"}
    assert api.post("/comptes-rendus", json=rappel_sans_date).status_code == 422
    produit_inconnu = {
        "client_id": "C010",
        "televendeur": "J",
        "issue": "commande",
        "lignes": [
            {
                "code": "ZZ",
                "libelle": "?",
                "origine": "stock",
                "reponse": "accepte",
                "quantite": 1,
                "prix_unitaire_ht": 1,
            }
        ],
    }
    reponse = api.post("/comptes-rendus", json=produit_inconnu)
    assert reponse.status_code == 422 and "ZZ" in reponse.json()["detail"]
    assert api.get("/statistiques", params={"jours": 0}).status_code == 422


def test_pilotage(api):
    file = api.get("/appels/file").json()
    assert len(file["appels"]) == 30
    assert all(
        a["client"]["commercial"] == "Karim Bensaïd"
        for a in api.get("/appels/file", params={"televendeur": "Karim Bensaïd"}).json()["appels"]
    )
    plan = api.get("/stock/plan-ecoulement").json()
    assert plan["lignes"] and plan["valeur_a_risque_ht"] > 0


def test_labo(api):
    agent = api.get("/labo/agent").json()
    assert "copilote" in agent["prompt_systeme"] and len(agent["outils"]) == 7
    outils = api.get("/labo/clients/C010/outils", params={"produit": "FR007"}).json()
    assert [o["nom"] for o in outils][-1] == "details_produit" and not any(o["est_erreur"] for o in outils)
    assert set(api.get("/labo/clients/C010/comparaison").json()) == {"simule", "repli"}


def test_types_typescript_a_jour():
    """Le frontend est typé à partir du schéma OpenAPI : le fichier généré doit être à jour."""
    assert SORTIE.read_text(encoding="utf-8") == generer(), "Lancez `python -m scripts.generer_types_ts`."
