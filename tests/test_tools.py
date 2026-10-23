"""Tests des outils métier (calculs déterministes)."""

from __future__ import annotations

import json

import pytest

from agent import tools
from datahub.base import ClientIntrouvable
from tests.conftest import produit


# --------------------------------------------------------------- historique_client


def test_historique_client_indicateurs(source_simple):
    h = tools.historique_client(source_simple, "R1")
    assert h["nb_commandes"] == 10
    # 10 × P1 (50 €) + 6 × P2 (20 €) + 1 × P3 (10 €) = 630 € sur 10 commandes
    assert h["panier_moyen_ht"] == 63.0
    assert h["ca_total_ht"] == 630.0
    assert h["intervalle_median_jours"] == 7
    assert h["jours_depuis_derniere_commande"] == 7
    assert h["jours_habituels"] == ["vendredi"]  # toutes les commandes tombent un vendredi
    assert h["prochain_jour_habituel"] == "vendredi 30/10"


def test_historique_client_produits_recurrents(source_simple):
    h = tools.historique_client(source_simple, "R1")
    recurrents = {p["code"]: p for p in h["produits_recurrents"]}
    assert set(recurrents) == {"P1", "P2"}  # P3 (1 seule commande) n'est pas récurrent
    assert recurrents["P1"]["frequence_pct"] == 100
    assert recurrents["P2"]["frequence_pct"] == 60
    assert recurrents["P1"]["quantite_habituelle"] == 5
    # trié par fréquence décroissante
    assert [p["code"] for p in h["produits_recurrents"]] == ["P1", "P2"]


def test_historique_client_sans_commande(source_simple):
    h = tools.historique_client(source_simple, "B1")
    assert h["nb_commandes"] == 0
    assert "message" in h


def test_historique_client_inconnu(source_simple):
    with pytest.raises(ClientIntrouvable):
        tools.historique_client(source_simple, "INCONNU")


# ------------------------------------------------------- produits_habituels_manquants


def test_produits_manquants_detecte_le_decrochage(source_simple):
    resultat = tools.produits_habituels_manquants(source_simple, "R1")
    codes = [p["code"] for p in resultat["produits"]]
    assert codes == ["P2"]  # P1 commandé il y a 7 jours (à jour), P3 occasionnel
    p2 = resultat["produits"][0]
    assert p2["rythme_habituel_jours"] == 7
    assert p2["jours_depuis_derniere_commande"] == 35
    assert p2["statut"] == "décroché"  # 35 j > 3 × 7 j
    assert p2["quantite_habituelle"] == 2


def test_produits_manquants_statut_en_retard(source_simple):
    # On avance la dernière commande de P2 : 14 jours, soit 2 × le rythme -> « en retard »
    for cmd in source_simple.commandes:
        if cmd.id == "A2":
            cmd.lignes.append(cmd.lignes[0].model_copy(update={"produit_code": "P2"}))
    p2 = tools.produits_habituels_manquants(source_simple, "R1")["produits"][0]
    assert p2["jours_depuis_derniere_commande"] == 14
    assert p2["statut"] == "en retard"


def test_produits_manquants_vide_si_a_jour(source_simple):
    assert tools.produits_habituels_manquants(source_simple, "R2")["produits"] == []


# ------------------------------------------------------------- remise et DLC


@pytest.mark.parametrize(
    "famille, jours, couverture, dlc_courte, attendu",
    [
        ("frais", 1, 5, True, 30),
        ("frais", 2, 5, True, 25),
        ("frais", 3, 5, True, 20),
        ("frais", 5, 5, True, 15),
        ("frais", 8, 5, False, 0),  # ni DLC courte ni surstock
        ("frais", 8, 20, False, 10),  # surstock (> 14 j)
        ("frais", 8, 40, False, 15),  # gros surstock (> 28 j)
        ("frais", 1, 40, True, 30),  # on garde la plus forte remise
        ("surgele", 25, 30, True, 15),
        ("surgele", 10, 30, True, 20),
        ("surgele", 200, 100, False, 10),
        ("surgele", 200, 400, False, 15),
    ],
)
def test_remise_suggeree(famille, jours, couverture, dlc_courte, attendu):
    assert tools.remise_suggeree(famille, jours, couverture, dlc_courte) == attendu


def test_remise_jamais_au_dela_du_plafond():
    for jours in range(1, 40):
        for couverture in (0, 10, 100, 1000, float("inf")):
            for famille in ("frais", "surgele"):
                assert 0 <= tools.remise_suggeree(famille, jours, couverture) <= tools.REMISE_MAX_PCT


@pytest.mark.parametrize("duree_vie, seuil", [(5, 2), (6, 2), (10, 3), (14, 4), (25, 5), (60, 5)])
def test_seuil_dlc_courte_frais(duree_vie, seuil):
    assert tools.seuil_dlc_courte(produit("X", duree_vie=duree_vie)) == seuil


def test_seuil_dlc_courte_surgele():
    assert tools.seuil_dlc_courte(produit("X", famille="surgele", duree_vie=365)) == 30


# ------------------------------------------------------------- stock_a_ecouler


def test_stock_a_ecouler_selectionne_les_produits_pertinents(source_simple):
    resultat = tools.stock_a_ecouler(source_simple, "R1")
    codes = [p["code"] for p in resultat["produits"]]
    # P1 : DLC demain et acheté chaque semaine par R1 -> proposé
    # P5 : DLC courte mais acheté par personne -> non pertinent
    # P4 : lot expiré ignoré, l'autre lot n'est ni en DLC courte ni en surstock
    assert codes == ["P1"]
    p1 = resultat["produits"][0]
    assert p1["lot_id"] == "L1"  # le lot à la DLC la plus proche
    assert p1["jours_avant_dlc"] == 1
    assert "DLC courte" in p1["motifs"]
    assert p1["remise_suggeree_pct"] == 30
    assert p1["prix_remise_ht"] == 7.0
    assert p1["pertinence"] == 3


def test_stock_a_ecouler_par_clients_similaires(source_simple):
    # P4 passe en DLC courte : R1 ne l'a jamais acheté, mais les 2 autres restaurants oui
    source_simple.lots[4] = source_simple.lots[4].model_copy(update={"dlc": source_simple.lots[0].dlc})
    produits = {p["code"]: p for p in tools.stock_a_ecouler(source_simple, "R1")["produits"]}
    assert produits["P4"]["pertinence"] == 1
    assert "Restaurant" in produits["P4"]["raison_pertinence"]


def test_stock_a_ecouler_respecte_la_limite(mock_source):
    for c in mock_source.get_clients()[:5]:
        assert len(tools.stock_a_ecouler(mock_source, c.id, limite=3)["produits"]) <= 3


# ---------------------------------------------------------- suggestions_croisees


def test_suggestions_croisees(source_simple):
    resultat = tools.suggestions_croisees(source_simple, "R1")
    assert resultat["nb_clients_similaires"] == 2
    assert [p["code"] for p in resultat["produits"]] == ["P4"]  # P1 déjà acheté : exclu
    assert resultat["produits"][0]["taux_adoption_pct"] == 100


def test_suggestions_croisees_sans_client_similaire(source_simple):
    resultat = tools.suggestions_croisees(source_simple, "B1")
    assert resultat["nb_clients_similaires"] == 0
    assert resultat["produits"] == []


# ------------------------------------------------------------ exposition à Claude


def test_definitions_outils_coherentes():
    noms = {d["name"] for d in tools.DEFINITIONS_OUTILS}
    assert noms == set(tools.FONCTIONS_OUTILS)
    for d in tools.DEFINITIONS_OUTILS:
        assert d["input_schema"]["required"] == ["client_id"]
        assert d["input_schema"]["additionalProperties"] is False


def test_executer_outil(source_simple):
    resultat = tools.executer_outil(source_simple, "historique_client", {"client_id": "R1"})
    assert resultat["nb_commandes"] == 10
    with pytest.raises(ValueError):
        tools.executer_outil(source_simple, "supprimer_commande", {"client_id": "R1"})


def test_resultats_serialisables_en_json(mock_source):
    """Les résultats d'outils partent tels quels à Claude : ils doivent être sérialisables."""
    for c in mock_source.get_clients():
        json.dumps(tools.contexte_complet(mock_source, c.id), ensure_ascii=False)
