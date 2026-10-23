"""Paramètres métier, regroupés en un seul objet immuable.

Toutes les règles de calcul (seuils, remises, fenêtres d'analyse) sont ici, et
nulle part ailleurs : c'est le seul fichier à modifier pour les calibrer avec
les équipes commerciales. Les tests peuvent injecter leurs propres règles.
"""

from __future__ import annotations

from dataclasses import dataclass, field

from copilote.domaine import Famille


@dataclass(frozen=True, slots=True)
class PoidsPriorite:
    """Points attribués à chaque signal pour classer les appels du jour (score plafonné à 100)."""

    rappel_du: int = 60  # rappel promis au client : priorité absolue
    jour_commande_aujourdhui: int = 30  # aujourd'hui est un de ses jours de commande
    jour_commande_demain: int = 15
    commande_en_retard: int = 20  # aucune commande depuis bien plus longtemps que d'habitude
    par_decrochage: int = 8
    max_decrochages: int = 16
    par_manquant: int = 3
    max_manquants: int = 9
    par_opportunite_stock: int = 4  # lot urgent intéressant pour ce client
    max_opportunites_stock: int = 12
    gros_client: int = 8  # tiers supérieur du chiffre d'affaires
    client_moyen: int = 4
    baisse_activite: int = 8
    seuil_baisse_activite_pct: int = -10
    seuil_haute: int = 50
    seuil_moyenne: int = 25


@dataclass(frozen=True, slots=True)
class ReglesMetier:
    # --- Historique et habitudes ---------------------------------------------------
    periode_analyse_jours: int = 183  # ~6 mois
    seuil_produit_recurrent: float = 0.30  # présent dans au moins 30 % des commandes…
    min_commandes_recurrent: int = 3  # … et au moins 3 fois
    seuil_jour_habituel: float = 0.20  # un jour de commande représentant ≥ 20 % des commandes
    semaines_tendance: int = 12  # tendance : 12 dernières semaines vs 12 précédentes

    # --- Produits manquants -----------------------------------------------------------
    facteur_retard: float = 1.5  # « manquant » au-delà de 1,5 × le rythme habituel
    retard_minimum_jours: int = 7
    facteur_decrochage: float = 3.0  # « décroché » au-delà de 3 × le rythme

    # --- Stock à écouler --------------------------------------------------------------
    fenetre_rotation_jours: int = 28
    dlc_courte_surgele_jours: int = 30
    part_duree_vie_dlc_courte: float = 0.30  # frais : 30 % de la durée de vie…
    dlc_courte_frais_min_jours: int = 2  # … bornée entre 2…
    dlc_courte_frais_max_jours: int = 5  # … et 5 jours
    seuil_surstock_jours: dict[Famille, int] = field(default_factory=lambda: {Famille.FRAIS: 14, Famille.SURGELE: 90})
    remise_max_pct: int = 30
    remises_dlc_courte_frais: dict[int, int] = field(default_factory=lambda: {1: 30, 2: 25, 3: 20})
    remise_dlc_courte_frais_defaut: int = 15
    remise_dlc_courte_surgele: int = 15
    remise_dlc_tres_courte_surgele: int = 20  # à 15 jours et moins
    remise_surstock: int = 10
    remise_gros_surstock: int = 15  # couverture > 2 × le seuil de surstock

    # --- Suggestions croisées ---------------------------------------------------------
    taux_adoption_min: float = 0.5  # adopté par au moins la moitié des clients similaires
    achats_min_adoption: int = 2  # « adopté » = acheté au moins 2 fois

    # --- Journal d'appels --------------------------------------------------------------
    jours_memoire_refus: int = 14  # un produit refusé n'est pas reproposé pendant 14 jours

    # --- Apprentissage des retours clients (acceptations et refus au téléphone) ------------
    apprentissage_fenetre_jours: int = 90
    apprentissage_min_propositions: int = 3  # pas de conclusion sur moins de 3 propositions
    apprentissage_lissage: int = 3  # taux lissé vers la moyenne (3 propositions « moyennes » fictives)
    apprentissage_ecart: float = 0.15  # écart à la moyenne retenu comme significatif (15 points)
    apprentissage_poids_pertinence: float = 0.5  # stock : une demi-marche de pertinence
    apprentissage_poids_adoption_pts: int = 20  # suggestions : 20 points de taux d'adoption

    # --- Objectifs du jour, par télévendeur ----------------------------------------------
    objectif_appels_jour: int = 20
    objectif_ca_jour_ht: float = 1500.0

    # --- Priorisation des appels -------------------------------------------------------
    priorite: PoidsPriorite = field(default_factory=PoidsPriorite)


REGLES_PAR_DEFAUT = ReglesMetier()
