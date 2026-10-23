"""Comptes-rendus d'appels saisis par les télévendeurs.

Ces données appartiennent au copilote (et non à l'ERP) : elles sont stockées
localement et servent à mesurer l'efficacité des propositions, à ne pas
reproposer un produit tout juste refusé et à nourrir la priorisation.
"""

from __future__ import annotations

from datetime import date, datetime
from enum import StrEnum
from typing import Self

from pydantic import BaseModel, ConfigDict, Field, model_validator


class Issue(StrEnum):
    """Issue de l'appel."""

    COMMANDE = "commande"
    PAS_DE_BESOIN = "pas_de_besoin"
    RAPPELER = "rappeler"
    INJOIGNABLE = "injoignable"


class Origine(StrEnum):
    """D'où vient la proposition faite au client."""

    MANQUANT = "manquant"
    STOCK = "stock"
    SUGGESTION = "suggestion"
    AUTRE = "autre"


class Reponse(StrEnum):
    ACCEPTE = "accepte"
    REFUSE = "refuse"
    SANS_REPONSE = "sans_reponse"


class LigneCompteRendu(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid", json_schema_serialization_defaults_required=True)

    code: str
    libelle: str
    unite: str = ""
    origine: Origine
    reponse: Reponse
    quantite: float = Field(ge=0)
    prix_unitaire_ht: float = Field(ge=0)
    remise_pct: int = Field(default=0, ge=0, le=100)

    @model_validator(mode="after")
    def _quantite_si_accepte(self) -> Self:
        if self.reponse is Reponse.ACCEPTE and self.quantite <= 0:
            raise ValueError(f"Quantité obligatoire pour un produit accepté ({self.code})")
        return self

    @property
    def prix_net_ht(self) -> float:
        return round(self.prix_unitaire_ht * (1 - self.remise_pct / 100), 2)

    @property
    def montant_ht(self) -> float:
        """Montant HT de la ligne si elle est acceptée, 0 sinon."""
        if self.reponse is not Reponse.ACCEPTE:
            return 0.0
        return round(self.quantite * self.prix_net_ht, 2)


class SaisieCompteRendu(BaseModel):
    """Compte-rendu tel que saisi dans l'interface (l'auteur est l'utilisateur connecté)."""

    model_config = ConfigDict(frozen=True, extra="forbid", json_schema_serialization_defaults_required=True)

    client_id: str
    issue: Issue
    notes: str = Field(default="", max_length=2000)
    rappel_le: date | None = None
    mode_fiche: str | None = Field(default=None, description="Mode de la fiche utilisée : ia, ia_simulee, repli")
    lignes: list[LigneCompteRendu] = Field(default_factory=list, max_length=50)

    @model_validator(mode="after")
    def _coherence(self) -> Self:
        if self.issue is Issue.RAPPELER and self.rappel_le is None:
            raise ValueError("Une date de rappel est obligatoire quand le client demande à être rappelé")
        if self.issue is Issue.COMMANDE and not any(l.reponse is Reponse.ACCEPTE for l in self.lignes):
            raise ValueError("Une issue « commande » suppose au moins un produit accepté")
        return self

    @property
    def montant_accepte_ht(self) -> float:
        return round(sum(l.montant_ht for l in self.lignes), 2)

    def par(self, televendeur: str) -> NouveauCompteRendu:
        """Attribue la saisie à son auteur."""
        return NouveauCompteRendu(**self.model_dump(), televendeur=televendeur)


class NouveauCompteRendu(SaisieCompteRendu):
    """Compte-rendu attribué à son auteur, prêt à être enregistré."""

    televendeur: str = Field(min_length=1)


class CompteRendu(NouveauCompteRendu):
    """Compte-rendu enregistré."""

    id: int
    cree_le: datetime
