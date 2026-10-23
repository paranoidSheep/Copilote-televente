"""Rapport de diagnostic des données : connexion au datahub, respect du contrat, qualité."""

from __future__ import annotations

from datetime import date, datetime
from enum import StrEnum

from pydantic import Field

from copilote.domaine import ModeleImmuable


class Gravite(StrEnum):
    CRITIQUE = "critique"  # fausserait les analyses : les enregistrements sont écartés
    ALERTE = "alerte"  # exploitable, mais résultats dégradés sur les éléments concernés
    INFO = "info"  # à connaître, sans effet sur la fiabilité des fiches


class Traitement(StrEnum):
    ECARTE = "ecarte"  # écarté automatiquement des analyses par le copilote
    SIGNALE = "signale"  # conservé tel quel : à corriger dans l'ERP


class StatutDiagnostic(StrEnum):
    CONFORME = "conforme"
    A_SURVEILLER = "a_surveiller"  # alertes seulement
    A_CORRIGER = "a_corriger"  # anomalies critiques ou contrat non respecté
    LECTURE_IMPOSSIBLE = "lecture_impossible"  # source injoignable, jeton refusé ou réponse non conforme


class MesureRessource(ModeleImmuable):
    """Lecture d'une ressource du datahub : durée et volume (ou erreur)."""

    ressource: str = Field(description="Identifiant technique, ex. « commandes »")
    libelle: str
    duree_ms: int
    volume: int | None = Field(description="Nombre d'éléments reçus ; null en cas d'erreur")
    erreur: str | None


class VerificationContrat(ModeleImmuable):
    """Un point du contrat d'interface vérifié sur la source réelle."""

    libelle: str
    reussie: bool
    detail: str


class Exemple(ModeleImmuable):
    identifiant: str = Field(description="Identifiant à rechercher dans l'ERP (client, commande, lot, produit)")
    detail: str


class ResultatRegle(ModeleImmuable):
    """Résultat d'une règle de qualité, avec quelques exemples à corriger."""

    code: str
    libelle: str
    gravite: Gravite
    traitement: Traitement
    impact: str = Field(description="Conséquence pour le copilote, en clair")
    nombre: int
    exemples: tuple[Exemple, ...]


class Volumes(ModeleImmuable):
    clients: int
    produits: int
    commandes: int
    lignes: int
    lots: int
    premiere_commande: date | None
    derniere_commande: date | None


class RapportDiagnostic(ModeleImmuable):
    source: str
    date_reference: date
    genere_le: datetime
    duree_totale_ms: int
    periode_analyse_jours: int
    statut: StatutDiagnostic
    resume: str
    connexion: tuple[MesureRessource, ...]
    contrat: tuple[VerificationContrat, ...]
    volumes: Volumes | None = Field(description="Volumes reçus ; null si la lecture a échoué")
    qualite: tuple[ResultatRegle, ...] = Field(description="Toutes les règles, y compris celles sans anomalie")
    enregistrements_ecartes: int
