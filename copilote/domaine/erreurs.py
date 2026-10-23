"""Erreurs métier du copilote, regroupées pour être traduites proprement par l'API."""

from __future__ import annotations


class ErreurCopilote(Exception):
    """Base de toutes les erreurs attendues du copilote."""


class ErreurSourceDonnees(ErreurCopilote):
    """Erreur d'accès à la source de données (configuration, réseau, format…)."""


class ClientIntrouvable(ErreurSourceDonnees):
    """Le client demandé n'existe pas."""

    def __init__(self, client_id: str) -> None:
        super().__init__(f"Client inconnu : {client_id}")
        self.client_id = client_id


class ProduitIntrouvable(ErreurCopilote):
    """Le produit demandé n'existe pas dans le catalogue."""

    def __init__(self, code: str) -> None:
        super().__init__(f"Produit inconnu : {code}")
        self.code = code


class ErreurConfiguration(ErreurCopilote):
    """Configuration invalide ou incomplète."""
