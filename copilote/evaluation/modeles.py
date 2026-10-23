"""Résultats du banc d'évaluation : une note par fiche, une synthèse par rédacteur, une campagne."""

from __future__ import annotations

from datetime import date, datetime
from enum import StrEnum

from pydantic import BaseModel, ConfigDict, Field

from copilote.config import ModeLLM
from copilote.domaine import ModeleImmuable
from copilote.fiche import Correction, ModeFiche, TypeCorrection


class TypeSignal(StrEnum):
    """Faits que toute bonne fiche doit faire ressortir."""

    MANQUANT_PRIORITAIRE = "manquant_prioritaire"  # produit habituel en retard, parmi les plus importants
    LOT_URGENT_HABITUEL = "lot_urgent_habituel"  # lot à DLC courte d'un produit que le client achète déjà
    RAPPEL_PROMIS = "rappel_promis"  # le client a demandé à être rappelé


class SignalCle(ModeleImmuable):
    type: TypeSignal
    libelle: str
    code: str | None
    couvert: bool = Field(description="Repris par le rédacteur lui-même (et non ajouté par un garde-fou)")


class ControleFormat(ModeleImmuable):
    libelle: str
    reussi: bool
    detail: str


class EvaluationFiche(ModeleImmuable):
    """Note d'une fiche, et tout ce qui l'explique."""

    client_id: str
    client_nom: str
    redacteur: ModeLLM
    modele: str | None
    mode_obtenu: ModeFiche
    repli_force: bool = Field(description="L'IA a échoué : la fiche a été rédigée par le mode repli")
    score_global: int = Field(ge=0, le=100)
    score_fidelite: int = Field(ge=0, le=100)
    score_couverture: int = Field(ge=0, le=100)
    score_format: int = Field(ge=0, le=100)
    corrections: tuple[Correction, ...]
    remises_hors_regle: tuple[str, ...] = Field(description="Remises citées dans le texte sans être proposées")
    signaux: tuple[SignalCle, ...]
    controles_format: tuple[ControleFormat, ...]
    duree_ms: int
    jetons_entree: int
    jetons_sortie: int
    cout_usd: float | None


class CompteCorrection(ModeleImmuable):
    type: TypeCorrection
    nombre: int


class CompteDefaut(ModeleImmuable):
    libelle: str
    nombre: int


class SyntheseRedacteur(ModeleImmuable):
    """Moyennes et totaux d'un rédacteur sur l'ensemble des clients évalués."""

    redacteur: ModeLLM
    modele: str | None
    nb_fiches: int
    score_global: float
    score_fidelite: float
    score_couverture: float
    score_format: float
    fiches_sans_defaut: int
    taux_repli_pct: int
    corrections: tuple[CompteCorrection, ...]
    remises_hors_regle: int
    signaux_couverts: int
    signaux_total: int
    defauts_format: tuple[CompteDefaut, ...]
    latence_mediane_ms: int
    latence_p95_ms: int
    jetons_entree_moyens: int
    jetons_sortie_moyens: int
    cout_total_usd: float | None
    cout_par_fiche_usd: float | None
    cout_projete: bool = Field(description="Coût estimé au tarif du modèle imité (IA simulée)")


class Campagne(ModeleImmuable):
    """Une exécution du banc : tous les clients demandés, avec chaque rédacteur demandé."""

    id: int | None
    lancee_le: datetime
    duree_ms: int
    empreinte_prompt: str = Field(description="Empreinte du prompt système et des outils : identifie leur version")
    source: str
    date_donnees: date
    syntheses: tuple[SyntheseRedacteur, ...]
    fiches: tuple[EvaluationFiche, ...]


class ResumeCampagne(ModeleImmuable):
    """Une campagne de l'historique, sans le détail par fiche."""

    id: int
    lancee_le: datetime
    duree_ms: int
    empreinte_prompt: str
    source: str
    date_donnees: date
    nb_clients: int
    syntheses: tuple[SyntheseRedacteur, ...]


class EtatEvaluation(StrEnum):
    EN_COURS = "en_cours"
    TERMINEE = "terminee"
    ECHOUEE = "echouee"


class SuiviEvaluation(ModeleImmuable):
    """Avancement de la campagne lancée depuis l'interface (exécutée en arrière-plan)."""

    etat: EtatEvaluation
    redacteurs: tuple[ModeLLM, ...]
    faites: int
    total: int
    lancee_le: datetime
    campagne_id: int | None
    erreur: str | None


class DemandeEvaluation(BaseModel):
    model_config = ConfigDict(extra="forbid", json_schema_serialization_defaults_required=True)

    redacteurs: list[ModeLLM] = Field(min_length=1, description="Rédacteurs à évaluer (simule, anthropic, repli)")
    clients: list[str] | None = Field(default=None, description="Clients à évaluer ; tous si absent")
