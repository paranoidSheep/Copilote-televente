"""Source de données simulée, lue depuis un fichier JSON.

Le fichier est produit par `scripts/generer_donnees_mock.py` (données fictives,
générées de façon déterministe). Cette source permet de faire tourner et de
démontrer le copilote sans aucun accès à l'ERP.
"""

from __future__ import annotations

import json
import os
from datetime import date
from pathlib import Path

from .base import Client, ClientIntrouvable, Commande, DataSource, DataSourceError, Lot, Produit

CHEMIN_PAR_DEFAUT = Path(__file__).resolve().parent / "donnees" / "mock_data.json"


class MockDataSource(DataSource):
    nom = "mock"

    def __init__(self, chemin: str | Path | None = None) -> None:
        chemin = Path(chemin or os.environ.get("MOCK_DATA_PATH") or CHEMIN_PAR_DEFAUT)
        if not chemin.exists():
            raise DataSourceError(
                f"Fichier de données simulées introuvable : {chemin}. "
                "Lancez `python scripts/generer_donnees_mock.py` pour le créer."
            )
        brut = json.loads(chemin.read_text(encoding="utf-8"))

        # Chargement unique en mémoire : le fichier fait environ 1 Mo.
        self._date_reference = date.fromisoformat(brut["meta"]["date_reference"])
        self._clients = {c["id"]: Client(**c) for c in brut["clients"]}
        self._produits = [Produit(**p) for p in brut["produits"]]
        self._commandes = sorted((Commande(**c) for c in brut["commandes"]), key=lambda c: (c.date, c.id))
        self._lots = [Lot(**l) for l in brut["lots"]]

    def get_clients(self) -> list[Client]:
        return list(self._clients.values())

    def get_client(self, client_id: str) -> Client:
        try:
            return self._clients[client_id]
        except KeyError:
            raise ClientIntrouvable(f"Client inconnu : {client_id}") from None

    def get_order_history(self, client_id: str | None = None, depuis: date | None = None) -> list[Commande]:
        if client_id is not None:
            self.get_client(client_id)  # lève ClientIntrouvable si besoin
        return [
            c
            for c in self._commandes
            if (client_id is None or c.client_id == client_id) and (depuis is None or c.date >= depuis)
        ]

    def get_products(self) -> list[Produit]:
        return list(self._produits)

    def get_stock(self) -> list[Lot]:
        return list(self._lots)

    def date_du_jour(self) -> date:
        # Date figée du jeu de données : la démo donne le même résultat tous les jours.
        return self._date_reference
