"""État du service et contexte de l'utilisateur connecté."""

from __future__ import annotations

from fastapi import APIRouter

from copilote import __version__
from copilote.api.dependances import ApplicationDep, UtilisateurDep
from copilote.api.schemas import ContexteSession, ModeDisponible, Sante
from copilote.comptes import Permission
from copilote.config import ModeLLM

routeur = APIRouter(tags=["système"])

LIBELLES_MODES = {
    ModeLLM.ANTHROPIC: "Claude (API Anthropic)",
    ModeLLM.SIMULE: "IA simulée (rejeu de rédactions Claude)",
    ModeLLM.REPLI: "Sans IA (gabarits)",
}


@routeur.get("/sante", response_model=Sante)
def sante() -> Sante:
    """Sonde publique pour la supervision et le conteneur (aucune donnée métier)."""
    return Sante(statut="ok", version=__version__)


@routeur.get("/session", response_model=ContexteSession)
def session(app: ApplicationDep, utilisateur: UtilisateurDep) -> ContexteSession:
    ref = app.referentiels.obtenir()
    return ContexteSession(
        utilisateur=utilisateur,
        permissions=[p for p in Permission if utilisateur.peut(p)],
        authentification=app.config.securite.authentification,
        version=__version__,
        source_donnees=app.referentiels.nom_source,
        date_du_jour=ref.date_du_jour,
        mode_par_defaut=app.fiches.mode_defaut,
        modes_disponibles=[
            ModeDisponible(mode=m, libelle=LIBELLES_MODES[m], modele=app.fiches.modele(m))
            for m in app.fiches.modes_disponibles
        ],
        televendeurs=app.pilotage.televendeurs(),
    )
