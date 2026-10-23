"""Diagnostic des données : connexion au datahub, respect du contrat, qualité.

Sert au premier branchement sur le vrai datahub, puis en exploitation : un
responsable voit en un écran si les données sont fiables, et l'équipe ERP
reçoit une liste précise d'enregistrements à corriger.
"""

from .modeles import (
    Exemple,
    Gravite,
    MesureRessource,
    RapportDiagnostic,
    ResultatRegle,
    StatutDiagnostic,
    Traitement,
    VerificationContrat,
    Volumes,
)
from .qualite import REGLES, DonneesBrutes, Regle, controler_qualite
from .rapport import diagnostiquer

__all__ = [
    "REGLES",
    "DonneesBrutes",
    "Exemple",
    "Gravite",
    "MesureRessource",
    "RapportDiagnostic",
    "Regle",
    "ResultatRegle",
    "StatutDiagnostic",
    "Traitement",
    "VerificationContrat",
    "Volumes",
    "controler_qualite",
    "diagnostiquer",
]
