"""Contrat entre l'agent et un fournisseur de LLM.

L'agent ne connaît que ces types : il ne dépend d'aucun SDK. Chaque
fournisseur (Claude via l'API Anthropic, IA simulée…) traduit ces types dans
son propre format et garde l'historique de conversation dans sa session.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from enum import StrEnum
from typing import Protocol

from pydantic import BaseModel, ConfigDict, JsonValue

from copilote.domaine import ErreurCopilote


class _Type(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid", json_schema_serialization_defaults_required=True)


class DefinitionOutil(_Type):
    nom: str
    description: str
    schema_entree: dict[str, JsonValue]


class AppelOutil(_Type):
    id: str
    nom: str
    arguments: dict[str, JsonValue]


class ResultatOutil(_Type):
    appel_id: str
    contenu: str  # JSON sérialisé, ou message d'erreur
    est_erreur: bool = False


class Usage(_Type):
    jetons_entree: int = 0
    jetons_sortie: int = 0


class Arret(StrEnum):
    """Pourquoi le modèle a rendu la main."""

    FIN = "fin"  # réponse terminée
    OUTILS = "outils"  # le modèle demande l'exécution d'outils
    REFUS = "refus"  # le modèle décline la requête
    LIMITE = "limite"  # réponse tronquée (limite de jetons)


class ReponseLLM(_Type):
    arret: Arret
    modele: str
    textes: list[str] = []
    appels: list[AppelOutil] = []
    usage: Usage = Usage()


type MessageUtilisateur = str | Sequence[ResultatOutil]


class ErreurFournisseurLLM(ErreurCopilote):
    """Le fournisseur n'a pas pu répondre (réseau, quota, configuration…).

    `raison` est une explication courte, affichable au télévendeur.
    """

    def __init__(self, raison: str) -> None:
        super().__init__(raison)
        self.raison = raison


class SessionLLM(Protocol):
    """Une conversation en cours ; la session conserve son propre historique."""

    def envoyer(self, message: MessageUtilisateur) -> ReponseLLM: ...


class FournisseurLLM(Protocol):
    @property
    def nom(self) -> str: ...

    @property
    def modele(self) -> str: ...

    def ouvrir_session(
        self, systeme: str, outils: Sequence[DefinitionOutil], metadonnees: Mapping[str, str]
    ) -> SessionLLM:
        """Démarre une conversation. `metadonnees` : contexte technique (ex. client_id)."""
        ...
