"""Panier proposé : la commande que le télévendeur suggère au client, ligne par ligne."""

from __future__ import annotations

from collections.abc import Sequence
from typing import Protocol

from copilote.journal import Origine

from .modeles import LignePanier, ManquantFiche, PanierPropose, StockFiche, SuggestionFiche

QUANTITE_ESSAI = 1.0  # une suggestion se propose « pour essayer »


class _Article(Protocol):
    @property
    def code(self) -> str: ...
    @property
    def libelle(self) -> str: ...
    @property
    def unite(self) -> str: ...
    @property
    def prix_unitaire_ht(self) -> float: ...


def _ligne(article: _Article, origine: Origine, quantite: float, remise: int = 0) -> LignePanier:
    prix_net = round(article.prix_unitaire_ht * (1 - remise / 100), 2)
    return LignePanier(
        code=article.code,
        libelle=article.libelle,
        unite=article.unite,
        origine=origine,
        quantite=quantite,
        prix_unitaire_ht=article.prix_unitaire_ht,
        remise_pct=remise,
        prix_net_ht=prix_net,
        montant_ht=round(prix_net * quantite, 2),
    )


def construire_panier(
    manquants: Sequence[ManquantFiche], stock: Sequence[StockFiche], suggestions: Sequence[SuggestionFiche]
) -> PanierPropose:
    # Un produit à la fois « manquant » et « à écouler » n'apparaît qu'une fois, avec sa remise.
    codes_stock = {s.code for s in stock}
    lignes = [
        *(_ligne(m, Origine.MANQUANT, m.quantite_habituelle) for m in manquants if m.code not in codes_stock),
        *(_ligne(s, Origine.STOCK, s.quantite_conseillee, s.remise_pct) for s in stock),
        *(_ligne(g, Origine.SUGGESTION, QUANTITE_ESSAI) for g in suggestions),
    ]
    return PanierPropose(lignes=lignes, total_ht=round(sum(l.montant_ht for l in lignes), 2))
