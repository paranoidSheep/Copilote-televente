"""Administration des données : diagnostic de la source (réservé aux responsables)."""

from __future__ import annotations

from fastapi import APIRouter

from copilote.api.dependances import ApplicationDep
from copilote.diagnostic import RapportDiagnostic

routeur = APIRouter(prefix="/admin", tags=["administration"])


@routeur.get("/diagnostic", response_model=RapportDiagnostic)
def diagnostic(app: ApplicationDep) -> RapportDiagnostic:
    """Lit la source sans cache, vérifie le contrat d'interface et contrôle la qualité des données.

    Lecture seule : rien n'est modifié, ni dans le datahub ni dans le copilote.
    """
    return app.diagnostic.executer()
