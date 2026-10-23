"""Structure de la fiche d'appel et de sa rédaction."""

from __future__ import annotations

from datetime import date, datetime
from enum import StrEnum

from pydantic import BaseModel, ConfigDict, Field

from copilote.analyses import (
    HabitudesClient,
    HistoriqueAppels,
    ProduitManquant,
    PropositionStock,
    SuggestionCroisee,
)
from copilote.domaine import Client
from copilote.journal import Origine

from .trace import TraceExecution

# ---------------------------------------------------------------------------------
# Rédaction : ce que produit l'IA (ou le mode repli). Ce modèle sert aussi de
# schéma à l'outil `soumettre_fiche` : tous les champs sont obligatoires.
# ---------------------------------------------------------------------------------


class _Strict(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid", json_schema_serialization_defaults_required=True)


class RedactionManquant(_Strict):
    code: str = Field(description="Code d'un produit renvoyé par produits_habituels_manquants")
    commentaire: str = Field(description="Une phrase courte, utile au téléphone")


class RedactionStock(_Strict):
    code: str = Field(description="Code d'un produit renvoyé par stock_a_ecouler")
    remise_pct: int = Field(description="Remise proposée, inférieure ou égale à remise_suggeree_pct")
    argument: str = Field(description="Une phrase courte et concrète")


class RedactionSuggestion(_Strict):
    code: str = Field(description="Code d'un produit renvoyé par suggestions_croisees")
    argument: str = Field(description="Une phrase courte et concrète")


class Redaction(_Strict):
    resume_habitudes: str = Field(description="2 ou 3 phrases factuelles sur les habitudes du client")
    produits_manquants: list[RedactionManquant] = Field(description="Au plus 5, par ordre d'importance")
    stock_a_ecouler: list[RedactionStock] = Field(description="2 à 4 produits, par ordre de priorité")
    suggestions: list[RedactionSuggestion] = Field(description="0 à 3 produits")
    accroches: list[str] = Field(description="2 ou 3 phrases prêtes à dire, en vouvoiement")
    points_attention: list[str] = Field(description="0 à 3 alertes utiles ; liste vide sinon")


# ---------------------------------------------------------------------------------
# Fiche finale
# ---------------------------------------------------------------------------------


class TypeCorrection(StrEnum):
    """Nature d'une correction appliquée par les garde-fous à la rédaction de l'IA."""

    PRODUIT_INCONNU = "produit_inconnu"  # code absent des analyses : invention écartée
    OFFRE_REFUSEE = "offre_refusee"  # offre refusée récemment par le client, retirée
    REMISE_PLAFONNEE = "remise_plafonnee"  # remise ramenée au maximum autorisé
    SELECTION_LIMITEE = "selection_limitee"  # trop de produits proposés
    STOCK_COMPLETE = "stock_complete"  # sélection de stock complétée depuis les analyses
    ACCROCHE_RETIREE = "accroche_retiree"  # accroche vantant une offre retirée
    ACCROCHES_LIMITEES = "accroches_limitees"
    ACCROCHES_COMPLETEES = "accroches_completees"
    RAPPEL_AJOUTE = "rappel_ajoute"  # rappel promis au client absent des points d'attention


class Correction(_Strict):
    type: TypeCorrection
    message: str
    codes: list[str] = Field(default=[], description="Produits concernés, s'il y a lieu")


class ModeFiche(StrEnum):
    IA = "ia"  # rédigée par Claude
    IA_SIMULEE = "ia_simulee"  # rédaction IA rejouée (démonstration sans clé)
    REPLI = "repli"  # rédigée par gabarits, sans IA


class ManquantFiche(ProduitManquant):
    commentaire: str


class StockFiche(PropositionStock):
    remise_pct: int
    prix_propose_ht: float
    quantite_conseillee: float
    argument: str


class SuggestionFiche(SuggestionCroisee):
    argument: str


class LignePanier(_Strict):
    code: str
    libelle: str
    unite: str
    origine: Origine
    quantite: float
    prix_unitaire_ht: float
    remise_pct: int
    prix_net_ht: float
    montant_ht: float


class PanierPropose(_Strict):
    """Proposition de commande à valider avec le client, à saisir ensuite dans l'ERP."""

    lignes: list[LignePanier]
    total_ht: float


class Fiche(BaseModel):
    model_config = ConfigDict(extra="forbid", json_schema_serialization_defaults_required=True)

    client: Client
    date_du_jour: date
    genere_le: datetime
    mode: ModeFiche
    modele: str | None = None
    avertissement: str | None = None
    resume_habitudes: str
    habitudes: HabitudesClient
    produits_manquants: list[ManquantFiche]
    stock_a_ecouler: list[StockFiche]
    suggestions: list[SuggestionFiche]
    accroches: list[str]
    points_attention: list[str]
    appels_precedents: HistoriqueAppels
    panier: PanierPropose
    garde_fous: list[Correction] = Field(default=[], description="Corrections appliquées à la rédaction")
    trace: TraceExecution | None = None
    texte: str = ""
