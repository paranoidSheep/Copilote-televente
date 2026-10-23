"""Trace d'exécution de la rédaction : ce que l'IA a fait, dans quel ordre, en combien de temps.

Affichée dans l'onglet « Coulisses de l'IA » de l'interface : utile pour
déboguer, et pour montrer qu'aucune donnée n'est inventée.
"""

from __future__ import annotations

from enum import StrEnum

from pydantic import BaseModel, ConfigDict


class TypeEtape(StrEnum):
    APPEL_LLM = "appel_llm"
    OUTIL = "outil"
    GARDE_FOU = "garde_fou"


class EtapeTrace(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid", json_schema_serialization_defaults_required=True)

    type: TypeEtape
    nom: str
    debut_ms: int  # depuis le début de la rédaction
    duree_ms: int
    resume: str  # une ligne lisible
    detail: str | None = None  # entrée/sortie (tronquées) pour le débogage
    jetons_entree: int | None = None
    jetons_sortie: int | None = None
    erreur: bool = False


class TraceExecution(BaseModel):
    model_config = ConfigDict(extra="forbid", json_schema_serialization_defaults_required=True)

    fournisseur: str
    modele: str
    etapes: list[EtapeTrace] = []
    duree_totale_ms: int = 0

    @property
    def jetons_entree(self) -> int:
        return sum(e.jetons_entree or 0 for e in self.etapes)

    @property
    def jetons_sortie(self) -> int:
        return sum(e.jetons_sortie or 0 for e in self.etapes)
