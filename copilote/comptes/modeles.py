"""Utilisateurs du copilote, rôles et permissions.

Les comptes appartiennent au copilote (et non à l'ERP). Le « nom affiché »
d'un télévendeur doit correspondre au champ `commercial` des clients dans
l'ERP : c'est ce lien qui lui attribue sa file d'appels.
"""

from __future__ import annotations

import re
from datetime import datetime
from enum import StrEnum

from pydantic import BaseModel, ConfigDict, Field, field_validator


class Role(StrEnum):
    TELEVENDEUR = "televendeur"
    RESPONSABLE = "responsable"  # pilotage : toutes les files, statistiques globales, labo
    ADMIN = "admin"  # comme responsable, plus la gestion technique


class Permission(StrEnum):
    VOIR_TOUTES_LES_FILES = "voir_toutes_les_files"
    VOIR_STATISTIQUES_GLOBALES = "voir_statistiques_globales"
    UTILISER_LE_LABO = "utiliser_le_labo"
    DIAGNOSTIQUER_LES_DONNEES = "diagnostiquer_les_donnees"


PERMISSIONS: dict[Role, frozenset[Permission]] = {
    Role.TELEVENDEUR: frozenset(),
    Role.RESPONSABLE: frozenset(Permission),
    Role.ADMIN: frozenset(Permission),
}

MOTIF_IDENTIFIANT = re.compile(r"^[a-z0-9][a-z0-9._-]{1,39}$")
LONGUEUR_MIN_MOT_DE_PASSE = 10


class Utilisateur(BaseModel):
    """Compte tel qu'exposé à l'application (jamais le hachage du mot de passe)."""

    model_config = ConfigDict(frozen=True, extra="forbid", json_schema_serialization_defaults_required=True)

    identifiant: str
    nom_affiche: str = Field(description="Pour un télévendeur : son nom tel qu'il figure dans l'ERP")
    role: Role
    actif: bool = True
    cree_le: datetime

    @field_validator("identifiant")
    @classmethod
    def _identifiant_valide(cls, valeur: str) -> str:
        if not MOTIF_IDENTIFIANT.match(valeur):
            raise ValueError("identifiant : 2 à 40 caractères parmi a-z, 0-9, « . », « _ », « - »")
        return valeur

    def peut(self, permission: Permission) -> bool:
        return self.actif and permission in PERMISSIONS[self.role]
