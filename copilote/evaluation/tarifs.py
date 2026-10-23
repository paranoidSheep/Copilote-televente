"""Tarifs publics de l'API Anthropic, pour estimer le coût d'une fiche.

Prix en dollars par million de jetons (tarifs de l'API Anthropic au 06/10/2026,
hors cache et hors traitement par lots). À mettre à jour si les tarifs évoluent :
le coût affiché n'est qu'une estimation, la facture fait foi.
"""

from __future__ import annotations

from dataclasses import dataclass

DATE_DES_TARIFS = "06/10/2026"


@dataclass(frozen=True, slots=True)
class Tarif:
    entree_par_million: float
    sortie_par_million: float


TARIFS: dict[str, Tarif] = {
    "claude-opus-5-5": Tarif(4.00, 20.00),
    "claude-sonnet-5-5": Tarif(2.00, 10.00),
    "claude-haiku-5-5": Tarif(0.10, 0.50),
}


def tarif(modele: str | None) -> Tarif | None:
    """Tarif d'un modèle ; « claude-sonnet-5-5 (simulé) » est estimé au tarif du modèle imité."""
    if not modele:
        return None
    return TARIFS.get(modele.split()[0])


def cout_usd(modele: str | None, jetons_entree: int, jetons_sortie: int) -> float | None:
    if (t := tarif(modele)) is None:
        return None
    return (jetons_entree * t.entree_par_million + jetons_sortie * t.sortie_par_million) / 1_000_000
