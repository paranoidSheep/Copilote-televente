"""Modèles propres à l'API (les autres réponses réutilisent directement les modèles métier)."""

from __future__ import annotations

from datetime import date

from pydantic import BaseModel, ConfigDict

from copilote.analyses import HabitudesClient, HistoriqueAppels
from copilote.config import ModeLLM
from copilote.domaine import Client
from copilote.journal import CompteRendu


class _Schema(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid", json_schema_serialization_defaults_required=True)


class ModeDisponible(_Schema):
    mode: ModeLLM
    libelle: str
    modele: str | None


class Sante(_Schema):
    statut: str
    version: str
    source_donnees: str
    date_du_jour: date
    mode_par_defaut: ModeLLM
    modes_disponibles: list[ModeDisponible]
    televendeurs: list[str]


class Client360(_Schema):
    """Vue complète d'un client : identité, habitudes chiffrées et historique des appels."""

    client: Client
    habitudes: HabitudesClient
    appels: HistoriqueAppels
    comptes_rendus: list[CompteRendu]


class CompteRenduEnregistre(_Schema):
    compte_rendu: CompteRendu
    texte_saisie_erp: str


class Erreur(_Schema):
    detail: str
