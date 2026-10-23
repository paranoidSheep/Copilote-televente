"""Modèles propres à l'API (les autres réponses réutilisent directement les modèles métier)."""

from __future__ import annotations

from datetime import date

from pydantic import BaseModel, ConfigDict, Field

from copilote.analyses import HabitudesClient, HistoriqueAppels
from copilote.comptes import Permission, Utilisateur
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
    """État public du service (sonde de supervision) : ne divulgue aucune donnée métier."""

    statut: str
    version: str


class ContexteSession(_Schema):
    """Ce que l'interface doit savoir pour l'utilisateur connecté."""

    utilisateur: Utilisateur
    permissions: list[Permission]
    authentification: bool
    version: str
    source_donnees: str
    date_du_jour: date
    mode_par_defaut: ModeLLM
    modes_disponibles: list[ModeDisponible]
    televendeurs: list[str]


class Identifiants(_Schema):
    identifiant: str = Field(min_length=1, max_length=40)
    mot_de_passe: str = Field(min_length=1, max_length=200)


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
