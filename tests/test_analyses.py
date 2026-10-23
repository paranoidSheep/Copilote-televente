"""Analyses métier : calculs déterministes sur des cas construits à la main et sur le mock."""

from __future__ import annotations

from dataclasses import replace
from datetime import date, datetime, timedelta

import pytest

from copilote.analyses import (
    REGLES_PAR_DEFAUT,
    JourSemaine,
    MotifEcoulement,
    NiveauPriorite,
    Pertinence,
    Referentiel,
    StatutManquant,
    analyser_habitudes,
    analyser_manquants,
    analyser_produit,
    analyser_stock_client,
    analyser_suggestions,
    construire_file_appels,
    construire_plan_ecoulement,
    remise_suggeree,
    resumer_appels,
    seuil_dlc_courte,
    situations_stock,
)
from copilote.domaine import ClientIntrouvable, Famille, ProduitIntrouvable
from copilote.journal import CompteRendu, Issue, LigneCompteRendu, Origine, Reponse
from tests.conftest import AUJOURD_HUI, produit


def compte_rendu(client_id: str, jours_avant: int, issue: Issue = Issue.PAS_DE_BESOIN, lignes=(), rappel=None):
    return CompteRendu(
        id=jours_avant,
        client_id=client_id,
        televendeur="Julie",
        issue=issue,
        rappel_le=rappel,
        lignes=list(lignes),
        cree_le=datetime.combine(AUJOURD_HUI - timedelta(days=jours_avant), datetime.min.time()),
    )


def refus(code: str, origine: Origine) -> LigneCompteRendu:
    return LigneCompteRendu(
        code=code, libelle=code, origine=origine, reponse=Reponse.REFUSE, quantite=0, prix_unitaire_ht=10
    )


# ------------------------------------------------------------------- habitudes


def test_habitudes_indicateurs(ref_simple):
    h = analyser_habitudes(ref_simple, "R1")
    assert h.nb_commandes == 10
    assert h.panier_moyen_ht == 63.0  # (10 × 50 + 6 × 20 + 10) / 10
    assert h.ca_total_ht == 630.0
    assert h.intervalle_median_jours == 7
    assert h.jours_depuis_derniere_commande == 7
    assert h.jours_habituels == [JourSemaine.VENDREDI]
    assert h.prochain_jour_habituel == date(2026, 10, 30)
    assert [p.code for p in h.produits_recurrents] == ["P1", "P2"]  # P3 : une seule commande
    assert h.produits_recurrents[0].frequence_pct == 100


def test_habitudes_sans_commande_et_client_inconnu(ref_simple):
    h = analyser_habitudes(ref_simple, "B1")
    assert h.nb_commandes == 0 and h.panier_moyen_ht is None and h.produits_recurrents == []
    with pytest.raises(ClientIntrouvable):
        analyser_habitudes(ref_simple, "INCONNU")


# ------------------------------------------------------------------- manquants


def test_manquants_detecte_le_decrochage(ref_simple):
    resultat = analyser_manquants(ref_simple, "R1")
    assert [m.code for m in resultat.produits] == ["P2"]
    p2 = resultat.produits[0]
    assert (p2.rythme_habituel_jours, p2.jours_depuis_derniere_commande) == (7, 35)
    assert p2.statut is StatutManquant.DECROCHE  # 35 j > 3 × 7 j


def test_manquants_en_retard_si_moins_de_trois_rythmes(source_simple):
    commandes = source_simple.commandes
    a2 = next(c for c in commandes if c.id == "A2")
    commandes[commandes.index(a2)] = a2.model_copy(
        update={"lignes": (*a2.lignes, a2.lignes[0].model_copy(update={"produit_code": "P2"}))}
    )
    p2 = analyser_manquants(Referentiel.charger(source_simple), "R1").produits[0]
    assert p2.jours_depuis_derniere_commande == 14
    assert p2.statut is StatutManquant.EN_RETARD


def test_manquants_vide_si_client_a_jour(ref_simple):
    assert analyser_manquants(ref_simple, "R2").produits == []


# ------------------------------------------------------------------- remises et DLC


@pytest.mark.parametrize(
    ("famille", "jours", "couverture", "dlc_courte", "attendu"),
    [
        (Famille.FRAIS, 1, 5, True, 30),
        (Famille.FRAIS, 2, 5, True, 25),
        (Famille.FRAIS, 3, 5, True, 20),
        (Famille.FRAIS, 5, 5, True, 15),
        (Famille.FRAIS, 8, 5, False, 0),
        (Famille.FRAIS, 8, 20, False, 10),  # surstock (> 14 j)
        (Famille.FRAIS, 8, 40, False, 15),  # gros surstock (> 28 j)
        (Famille.FRAIS, 8, None, False, 15),  # aucune vente récente : stock dormant
        (Famille.FRAIS, 1, 40, True, 30),  # la plus forte remise l'emporte
        (Famille.SURGELE, 25, 30, True, 15),
        (Famille.SURGELE, 10, 30, True, 20),
        (Famille.SURGELE, 200, 100, False, 10),
        (Famille.SURGELE, 200, 400, False, 15),
    ],
)
def test_remise_suggeree(famille, jours, couverture, dlc_courte, attendu):
    assert remise_suggeree(famille, jours, couverture, dlc_courte, REGLES_PAR_DEFAUT) == attendu


def test_remise_jamais_au_dela_du_plafond():
    for jours in range(1, 40):
        for couverture in (0, 10, 100, 1000, None):
            for famille in Famille:
                for courte in (True, False):
                    assert 0 <= remise_suggeree(famille, jours, couverture, courte, REGLES_PAR_DEFAUT) <= 30


def test_plafond_parametrable():
    regles = replace(REGLES_PAR_DEFAUT, remise_max_pct=20)
    assert remise_suggeree(Famille.FRAIS, 1, 5, True, regles) == 20


@pytest.mark.parametrize(("duree_vie", "seuil"), [(5, 2), (6, 2), (10, 3), (14, 4), (25, 5), (60, 5)])
def test_seuil_dlc_courte_frais(duree_vie, seuil):
    assert seuil_dlc_courte(produit("X", duree_vie=duree_vie), REGLES_PAR_DEFAUT) == seuil


def test_seuil_dlc_courte_surgele():
    assert seuil_dlc_courte(produit("X", famille=Famille.SURGELE, duree_vie=365), REGLES_PAR_DEFAUT) == 30


# ------------------------------------------------------------------- stock


def test_situations_stock(ref_simple):
    situations = {s.code: s for s in situations_stock(ref_simple)}
    assert situations["P1"].lot_id == "L1"  # lot à la DLC la plus proche
    assert MotifEcoulement.DLC_COURTE in situations["P1"].motifs
    assert situations["P1"].remise_suggeree_pct == 30
    assert situations["P5"].couverture_jours is None  # jamais vendu
    assert "P4" not in situations  # lot expiré ignoré, l'autre n'est ni court ni en surstock
    assert situations_stock(ref_simple) is situations_stock(ref_simple)  # mémorisé par instantané


def test_stock_pertinent_pour_le_client(ref_simple):
    produits = analyser_stock_client(ref_simple, "R1").produits
    assert [p.code for p in produits] == ["P1"]  # P5 n'intéresse personne
    assert produits[0].pertinence is Pertinence.HABITUEL
    assert produits[0].prix_remise_ht == 7.0


def test_stock_pertinent_par_clients_similaires(source_simple):
    source_simple.lots[4] = source_simple.lots[4].model_copy(update={"dlc": source_simple.lots[0].dlc})
    produits = {p.code: p for p in analyser_stock_client(Referentiel.charger(source_simple), "R1").produits}
    assert produits["P4"].pertinence is Pertinence.CLIENTS_SIMILAIRES
    assert "Restaurant" in produits["P4"].raison_pertinence


def test_stock_respecte_la_limite(ref_mock):
    assert all(len(analyser_stock_client(ref_mock, c, limite=3).produits) <= 3 for c in list(ref_mock.clients)[:5])


# ------------------------------------------------------------------- suggestions


def test_suggestions_croisees(ref_simple):
    resultat = analyser_suggestions(ref_simple, "R1")
    assert resultat.nb_clients_similaires == 2
    assert [p.code for p in resultat.produits] == ["P4"]
    assert resultat.produits[0].taux_adoption_pct == 100


def test_suggestions_sans_client_similaire(ref_simple):
    assert analyser_suggestions(ref_simple, "B1").produits == []


# ------------------------------------------------------------------- détail produit


def test_details_produit(ref_simple):
    d = analyser_produit(ref_simple, "R1", "P1")
    assert d.nb_commandes_client == 10 and d.quantite_habituelle == 5
    assert [l.id for l in d.lots] == ["L1", "L2"]
    assert d.situation_stock is not None and d.pertinence is Pertinence.HABITUEL
    with pytest.raises(ProduitIntrouvable):
        analyser_produit(ref_simple, "R1", "XX")


# ------------------------------------------------------------------- appels précédents


def test_memoire_des_refus_limitee_aux_offres(ref_simple):
    crs = [compte_rendu("R1", 2, lignes=[refus("P1", Origine.STOCK), refus("P2", Origine.MANQUANT)])]
    historique = resumer_appels(crs, "R1", AUJOURD_HUI, REGLES_PAR_DEFAUT)
    assert historique.codes_refuses_recemment == ["P1"]  # un produit habituel refusé reste habituel


def test_refus_oublies_apres_quatorze_jours(ref_simple):
    crs = [compte_rendu("R1", 20, lignes=[refus("P1", Origine.STOCK)])]
    assert resumer_appels(crs, "R1", AUJOURD_HUI, REGLES_PAR_DEFAUT).codes_refuses_recemment == []


def test_rappel_pris_en_compte_seulement_au_dernier_appel():
    rappel = compte_rendu("R1", 3, Issue.RAPPELER, rappel=AUJOURD_HUI)
    assert resumer_appels([rappel], "R1", AUJOURD_HUI, REGLES_PAR_DEFAUT).rappel_prevu == AUJOURD_HUI
    traite = compte_rendu("R1", 1, Issue.PAS_DE_BESOIN)
    assert resumer_appels([rappel, traite], "R1", AUJOURD_HUI, REGLES_PAR_DEFAUT).rappel_prevu is None


# ------------------------------------------------------------------- priorisation


def test_file_appels_ordonnee_et_expliquee(ref_mock):
    file = construire_file_appels(ref_mock, [])
    scores = [a.score for a in file.appels]
    assert scores == sorted(scores, reverse=True)
    assert all(0 <= s <= 100 for s in scores)
    premier = file.appels[0]
    assert premier.niveau is NiveauPriorite.HAUTE
    assert sum(r.points for r in premier.raisons) >= premier.score  # score = somme plafonnée


def test_rappel_promis_en_tete_et_deja_appele_en_fin(ref_mock):
    cible, appele = "C016", "C003"
    crs = [
        compte_rendu(cible, 1, Issue.RAPPELER, rappel=AUJOURD_HUI),
        compte_rendu(appele, 0, Issue.PAS_DE_BESOIN),
    ]
    file = construire_file_appels(ref_mock, crs)
    rappele = next(a for a in file.appels if a.client.id == cible)
    assert rappele.raisons[0].code == "rappel"
    assert rappele.score >= REGLES_PAR_DEFAUT.priorite.rappel_du
    assert rappele.niveau is NiveauPriorite.HAUTE
    assert file.appels[-1].client.id == appele and file.appels[-1].deja_appele_aujourdhui
    assert appele not in {a.client.id for a in file.restants}


def test_file_filtree_par_televendeur(ref_mock):
    file = construire_file_appels(ref_mock, [], televendeur="Julie Moreau")
    assert file.appels and all(a.client.commercial == "Julie Moreau" for a in file.appels)


# ------------------------------------------------------------------- plan d'écoulement


def test_plan_ecoulement(ref_mock):
    plan = construire_plan_ecoulement(ref_mock, max_clients=5)
    assert plan.lignes and plan.nb_lots_urgents > 0 and plan.valeur_a_risque_ht > 0
    for ligne in plan.lignes:
        assert len(ligne.clients) <= 5
        assert 0 <= ligne.couverture_plan_pct <= 100
        pertinences = [c.pertinence for c in ligne.clients]
        assert pertinences == sorted(pertinences, reverse=True)
        assert all(p is not Pertinence.AUCUNE for p in pertinences)


def test_referentiel_index(ref_simple):
    assert [c.id for c in ref_simple.clients_similaires("R1")] == ["R2", "R3"]
    assert set(ref_simple.produits_recurrents("R1")) == {"P1", "P2"}
    assert ref_simple.ventes_journalieres["P1"] == pytest.approx((4 * 5 + 4 + 3) / 28)
