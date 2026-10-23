"""Objets métier lus dans l'ERP via le datahub.

Ces modèles sont immuables (`frozen`) : une fois chargées, les données de
référence ne sont jamais modifiées par le copilote.
"""

from __future__ import annotations

from datetime import date
from enum import StrEnum

from pydantic import BaseModel, ConfigDict, Field, computed_field


class ModeleImmuable(BaseModel):
    """Base des objets de référence : immuables, champs inconnus refusés."""

    model_config = ConfigDict(frozen=True, extra="forbid", json_schema_serialization_defaults_required=True)


class Famille(StrEnum):
    FRAIS = "frais"
    SURGELE = "surgele"


class Client(ModeleImmuable):
    """Un client professionnel (restaurant, cantine, boulangerie…)."""

    id: str
    nom: str
    type: str = Field(description="Type d'établissement, ex. « Restaurant », « Cantine scolaire »")
    ville: str
    contact: str = Field(description="Interlocuteur habituel")
    telephone: str
    commercial: str = Field(description="Télévendeur en charge du compte")


class Produit(ModeleImmuable):
    """Un article du catalogue."""

    code: str
    libelle: str
    categorie: str
    famille: Famille
    unite: str = Field(description="Unité de vente : kg, colis, carton, bac…")
    prix_unitaire_ht: float = Field(ge=0)
    duree_vie_jours: int = Field(ge=0, description="Durée de vie typique entre réception et DLC")


class LigneCommande(ModeleImmuable):
    produit_code: str
    quantite: float = Field(gt=0)
    prix_unitaire_ht: float = Field(ge=0)

    @property
    def montant_ht(self) -> float:
        return self.quantite * self.prix_unitaire_ht


class Commande(ModeleImmuable):
    """Une commande client passée (historique)."""

    id: str
    client_id: str
    date: date
    lignes: tuple[LigneCommande, ...]

    @computed_field  # type: ignore[prop-decorator]
    @property
    def montant_ht(self) -> float:
        return round(sum(ligne.montant_ht for ligne in self.lignes), 2)

    @property
    def codes_produits(self) -> frozenset[str]:
        return frozenset(ligne.produit_code for ligne in self.lignes)


class Lot(ModeleImmuable):
    """Un lot physique en stock, avec sa date limite de consommation (DLC)."""

    id: str
    produit_code: str
    quantite: float = Field(ge=0)
    dlc: date
    date_reception: date
    entrepot: str
