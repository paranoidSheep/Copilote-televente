"""Assemblage de l'application : construit tous les services à partir de la configuration.

C'est le seul endroit où les implémentations concrètes sont choisies (source
de données, stockage du journal, fournisseurs d'IA). Les tests y injectent
leurs propres composants.
"""

from __future__ import annotations

import logging
import secrets
from collections.abc import Mapping
from dataclasses import dataclass
from datetime import timedelta

from copilote.agent.llm import FournisseurClaude, FournisseurLLM, FournisseurSimule, ParametresClaude
from copilote.analyses import REGLES_PAR_DEFAUT, ReglesMetier
from copilote.comptes import DepotUtilisateurs, DepotUtilisateursSQLite, ServiceComptes, SignataireSessions
from copilote.config import Config, ModeLLM
from copilote.datahub import DataSource, creer_source
from copilote.evaluation import DepotEvaluations, DepotEvaluationsSQLite
from copilote.horloge import Horloge, HorlogeAlignee
from copilote.journal import DepotJournal, DepotSQLite
from copilote.services import (
    FournisseurReferentiel,
    ServiceDiagnostic,
    ServiceEvaluation,
    ServiceFiches,
    ServiceJournal,
    ServicePilotage,
)

journal_app = logging.getLogger("copilote")


@dataclass(frozen=True)
class Application:
    config: Config
    referentiels: FournisseurReferentiel
    fiches: ServiceFiches
    journal: ServiceJournal
    pilotage: ServicePilotage
    comptes: ServiceComptes
    diagnostic: ServiceDiagnostic
    evaluation: ServiceEvaluation


def signataire_sessions(config: Config) -> SignataireSessions:
    secret = config.securite.secret_session
    if secret is None:
        # Acceptable sur un poste de développement ; en production, SESSION_SECRET est obligatoire.
        journal_app.warning("SESSION_SECRET absent : secret éphémère, les sessions ne survivront pas au redémarrage.")
        secret = secrets.token_urlsafe(48)
    return SignataireSessions(secret, timedelta(hours=config.securite.duree_session_heures))


def fournisseurs_par_defaut(config: Config) -> dict[ModeLLM, FournisseurLLM]:
    """IA simulée toujours disponible ; Claude seulement si une clé est configurée."""
    fournisseurs: dict[ModeLLM, FournisseurLLM] = {
        ModeLLM.SIMULE: FournisseurSimule(latence_ms=config.latence_simulee_ms)
    }
    if config.cle_anthropic_presente:
        fournisseurs[ModeLLM.ANTHROPIC] = FournisseurClaude(ParametresClaude(modele=config.modele_anthropic))
    return fournisseurs


def creer_application(
    config: Config,
    *,
    source: DataSource | None = None,
    depot_journal: DepotJournal | None = None,
    fournisseurs: Mapping[ModeLLM, FournisseurLLM] | None = None,
    horloge: Horloge | None = None,
    depot_utilisateurs: DepotUtilisateurs | None = None,
    depot_evaluations: DepotEvaluations | None = None,
    regles: ReglesMetier = REGLES_PAR_DEFAUT,
) -> Application:
    source = source or creer_source(config)
    depot = depot_journal or DepotSQLite(config.chemin_journal)
    horloge = horloge or HorlogeAlignee(source.date_du_jour)
    referentiels = FournisseurReferentiel(source, regles, config.duree_cache_secondes)
    fiches = ServiceFiches(
        referentiels,
        depot,
        fournisseurs if fournisseurs is not None else fournisseurs_par_defaut(config),
        config.mode_llm_effectif,
        horloge,
    )
    return Application(
        config=config,
        referentiels=referentiels,
        fiches=fiches,
        journal=ServiceJournal(depot, referentiels, horloge, apres_enregistrement=fiches.invalider),
        pilotage=ServicePilotage(referentiels, depot),
        comptes=ServiceComptes(
            depot_utilisateurs or DepotUtilisateursSQLite(config.chemin_utilisateurs), signataire_sessions(config)
        ),
        diagnostic=ServiceDiagnostic(source, regles),
        evaluation=ServiceEvaluation(
            fiches, referentiels, depot_evaluations or DepotEvaluationsSQLite(config.chemin_evaluations)
        ),
    )
