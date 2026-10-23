"""Panier proposé : la commande que le télévendeur suggère au client, ligne par ligne."""

from __future__ import annotations

from collections.abc import Sequence

from copilote.journal import Origine

from .modeles import LignePanier, ManquantFiche, PanierPropose, StockFiche, SuggestionFiche

QUANTITE_ESSAI = 1.0  # une suggestion se propose « pour essayer »


def _ligne(
    code: str, libelle: str, unite: str, origine: Origine, quantite: float, prix: float, remise: int
) -> LignePanier:
    prix_net = round(prix * (1 - remise / 100), 2)
    return LignePanier(
        code=code,
        libelle=libelle,
        unite=unite,
        origine=origine,
        quantite=quantite,
        prix_unitaire_ht=prix,
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
        *(
            _ligne(m.code, m.libelle, m.unite, Origine.MANQUANT, m.quantite_habituelle, m.prix_unitaire_ht, 0)
            for m in manquants
            if m.code not in codes_stock
        ),
        *(
            _ligne(s.code, s.libelle, s.unite, Origine.STOCK, s.quantite_conseillee, s.prix_unitaire_ht, s.remise_pct)
            for s in stock
        ),
        *(
            _ligne(g.code, g.libelle, g.unite, Origine.SUGGESTION, QUANTITE_ESSAI, g.prix_unitaire_ht, 0)
            for g in suggestions
        ),
    ]
    return PanierPropose(lignes=lignes, total_ht=round(sum(l.montant_ht for l in lignes), 2))
