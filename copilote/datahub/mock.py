"""Source de données simulée, lue depuis un fichier JSON généré par
`scripts/generer_donnees_mock.py` (données fictives, déterministes)."""

from __future__ import annotations

import json
from datetime import date
from pathlib import Path

from pydantic import BaseModel, ConfigDict, ValidationError

from copilote.domaine import Client, ClientIntrouvable, Commande, ErreurSourceDonnees, Lot, Produit

from .base import DataSource

CHEMIN_PAR_DEFAUT = Path(__file__).resolve().parent / "donnees" / "mock_data.json"


class _Meta(BaseModel):
    model_config = ConfigDict(extra="ignore", json_schema_serialization_defaults_required=True)
    date_reference: date


class _FichierMock(BaseModel):
    """Structure attendue du fichier JSON (validée au chargement)."""

    model_config = ConfigDict(extra="forbid", json_schema_serialization_defaults_required=True)
    meta: _Meta
    clients: list[Client]
    produits: list[Produit]
    commandes: list[Commande]
    lots: list[Lot]


class MockDataSource(DataSource):
    nom = "mock"

    def __init__(self, chemin: Path | None = None) -> None:
        chemin = chemin or CHEMIN_PAR_DEFAUT
        if not chemin.exists():
            raise ErreurSourceDonnees(
                f"Fichier de données simulées introuvable : {chemin}. "
                "Lancez `python -m scripts.generer_donnees_mock` pour le créer."
            )
        try:
            fichier = _FichierMock.model_validate(json.loads(chemin.read_text(encoding="utf-8")))
        except (ValidationError, json.JSONDecodeError) as exc:
            raise ErreurSourceDonnees(f"Fichier de données simulées invalide ({chemin}) : {exc}") from exc

        self._date_reference = fichier.meta.date_reference
        self._clients = {c.id: c for c in fichier.clients}
        self._produits = fichier.produits
        self._commandes = sorted(fichier.commandes, key=lambda c: (c.date, c.id))
        self._lots = fichier.lots

    def get_clients(self) -> list[Client]:
        return list(self._clients.values())

    def get_client(self, client_id: str) -> Client:
        try:
            return self._clients[client_id]
        except KeyError:
            raise ClientIntrouvable(client_id) from None

    def get_order_history(self, client_id: str | None = None, depuis: date | None = None) -> list[Commande]:
        if client_id is not None:
            self.get_client(client_id)
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
        return self._date_reference
