"""État du service."""

from __future__ import annotations

from fastapi import APIRouter

from copilote import __version__
from copilote.api.dependances import ApplicationDep
from copilote.api.schemas import ModeDisponible, Sante
from copilote.config import ModeLLM

routeur = APIRouter(tags=["système"])

LIBELLES_MODES = {
    ModeLLM.ANTHROPIC: "Claude (API Anthropic)",
    ModeLLM.SIMULE: "IA simulée (rejeu de rédactions Claude)",
    ModeLLM.REPLI: "Sans IA (gabarits)",
}


@routeur.get("/sante", response_model=Sante)
def sante(app: ApplicationDep) -> Sante:
    ref = app.referentiels.obtenir()
    return Sante(
        statut="ok",
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
