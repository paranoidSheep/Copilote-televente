"""Accès aux données ERP via le datahub (lecture seule).

`get_datasource()` choisit l'implémentation selon la variable d'environnement
DATASOURCE : `mock` (défaut, données simulées) ou `http` (vrai datahub).
"""

from __future__ import annotations

import os

from .base import Client, ClientIntrouvable, Commande, DataSource, DataSourceError, LigneCommande, Lot, Produit

__all__ = [
    "Client",
    "ClientIntrouvable",
    "Commande",
    "DataSource",
    "DataSourceError",
    "LigneCommande",
    "Lot",
    "Produit",
    "get_datasource",
]


def get_datasource(nom: str | None = None) -> DataSource:
    """Instancie la source de données configurée."""
    nom = (nom or os.environ.get("DATASOURCE", "mock")).strip().lower()
    if nom == "mock":
        from .mock import MockDataSource

        return MockDataSource()
    if nom == "http":
        from .http import HttpDataSource

        return HttpDataSource()
    raise DataSourceError(f"DATASOURCE inconnue : {nom!r} (valeurs possibles : mock, http)")
