"""Banc d'évaluation de la qualité des fiches : critères, synthèse, historique et rapport.

Mesure objectivement chaque rédacteur (Claude, IA simulée, repli) sur des
critères vérifiables, pour comparer deux versions du prompt avant de les
mettre en production.
"""

from .criteres import evaluer_fiche
from .depot import CampagneIntrouvable, DepotEvaluations, DepotEvaluationsMemoire, DepotEvaluationsSQLite
from .modeles import (
    Campagne,
    CompteCorrection,
    CompteDefaut,
    ControleFormat,
    DemandeEvaluation,
    EtatEvaluation,
    EvaluationFiche,
    ResumeCampagne,
    SignalCle,
    SuiviEvaluation,
    SyntheseRedacteur,
    TypeSignal,
)
from .rapport import en_markdown
from .synthese import synthetiser

__all__ = [
    "Campagne",
    "CampagneIntrouvable",
    "CompteCorrection",
    "CompteDefaut",
    "ControleFormat",
    "DemandeEvaluation",
    "DepotEvaluations",
    "DepotEvaluationsMemoire",
    "DepotEvaluationsSQLite",
    "EtatEvaluation",
    "EvaluationFiche",
    "ResumeCampagne",
    "SignalCle",
    "SuiviEvaluation",
    "SyntheseRedacteur",
    "TypeSignal",
    "en_markdown",
    "evaluer_fiche",
    "synthetiser",
]
