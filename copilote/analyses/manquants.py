"""Produits habituels du client pas encore commandés sur la période en cours."""

from __future__ import annotations

from datetime import date
from enum import StrEnum

from .base import Resultat
from .referentiel import Referentiel


class StatutManquant(StrEnum):
    EN_RETARD = "en_retard"
    DECROCHE = "decroche"  # probablement acheté chez un concurrent


class ProduitManquant(Resultat):
    code: str
    libelle: str
    unite: str
    prix_unitaire_ht: float
    frequence_pct: int
    rythme_habituel_jours: float
    derniere_commande: date
    jours_depuis_derniere_commande: int
    quantite_habituelle: float
    retard_ratio: float
    statut: StatutManquant


class ProduitsManquants(Resultat):
    client_id: str
    date_du_jour: date
    regle: str
    produits: list[ProduitManquant]


def analyser_manquants(ref: Referentiel, client_id: str) -> ProduitsManquants:
    """Produits habituels non commandés depuis plus longtemps que leur rythme habituel.

    La « période en cours » est propre à chaque produit : c'est son rythme
    habituel d'achat chez ce client. Un produit est signalé quand il n'a pas été
    commandé depuis plus de `facteur_retard` fois ce rythme (et au moins
    `retard_minimum_jours`). Au-delà de `facteur_decrochage` fois le rythme, il
    est « décroché » : le client l'achète probablement ailleurs.
    """
    regles = ref.regles
    manquants: list[ProduitManquant] = []
    for r in ref.produits_recurrents(client_id).values():
        rythme = r.rythme_jours
        produit = ref.produits.get(r.code)
        if rythme is None or rythme <= 0 or produit is None:
            continue
        jours_depuis = (ref.date_du_jour - r.derniere_commande).days
        if jours_depuis <= max(regles.retard_minimum_jours, rythme * regles.facteur_retard):
            continue
        manquants.append(
            ProduitManquant(
                code=r.code,
                libelle=produit.libelle,
                unite=produit.unite,
                prix_unitaire_ht=produit.prix_unitaire_ht,
                frequence_pct=round(r.frequence * 100),
                rythme_habituel_jours=rythme,
                derniere_commande=r.derniere_commande,
                jours_depuis_derniere_commande=jours_depuis,
                quantite_habituelle=r.quantite_habituelle,
                retard_ratio=round(jours_depuis / rythme, 1),
                statut=(
                    StatutManquant.DECROCHE
                    if jours_depuis > rythme * regles.facteur_decrochage
                    else StatutManquant.EN_RETARD
                ),
            )
        )

    # Les plus importants d'abord : fréquence élevée et retard marqué (plafonné)
    manquants.sort(key=lambda m: (-(m.frequence_pct * min(m.retard_ratio, 5)), m.code))
    return ProduitsManquants(
        client_id=client_id,
        date_du_jour=ref.date_du_jour,
        regle=(
            f"Produit présent dans au moins {round(regles.seuil_produit_recurrent * 100)} % des commandes, "
            f"non commandé depuis plus de {regles.facteur_retard} × son rythme habituel "
            f"(minimum {regles.retard_minimum_jours} jours)."
        ),
        produits=manquants,
    )
