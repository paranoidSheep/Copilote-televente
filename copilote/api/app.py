"""Application FastAPI : assemblage des routeurs, gestion des erreurs, interface web.

Lancement :
    python -m copilote                                    # http://localhost:8000
    uvicorn copilote.api.app:creer_app --factory --reload
"""

from __future__ import annotations

import logging
from pathlib import Path

from fastapi import FastAPI, Request, status
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles

from copilote import __version__
from copilote.application import Application, creer_application
from copilote.config import Config
from copilote.domaine import (
    ClientIntrouvable,
    ErreurConfiguration,
    ErreurCopilote,
    ErreurSourceDonnees,
    ProduitIntrouvable,
)
from copilote.services import ErreurValidation

from .routes import appels, clients, labo, stock, systeme

DOSSIER_STATIQUE = Path(__file__).resolve().parent / "static"
journal = logging.getLogger("copilote")

# Traduction des erreurs métier en codes HTTP (du plus spécifique au plus général)
CODES_ERREURS: list[tuple[type[ErreurCopilote], int]] = [
    (ClientIntrouvable, status.HTTP_404_NOT_FOUND),
    (ProduitIntrouvable, status.HTTP_404_NOT_FOUND),
    (ErreurValidation, status.HTTP_422_UNPROCESSABLE_CONTENT),
    (ErreurSourceDonnees, status.HTTP_502_BAD_GATEWAY),
    (ErreurConfiguration, status.HTTP_500_INTERNAL_SERVER_ERROR),
]


def creer_app(application: Application | None = None) -> FastAPI:
    app = FastAPI(
        title="Copilote télévente",
        description=(
            "Fiches d'appel, file d'appels priorisée et plan d'écoulement du stock, "
            "à partir des données ERP (lecture seule)."
        ),
        version=__version__,
    )
    app.state.application = application or creer_application(Config.depuis_environnement())

    @app.exception_handler(ErreurCopilote)
    async def erreur_metier(_requete: Request, exc: ErreurCopilote) -> JSONResponse:
        code = next((c for type_, c in CODES_ERREURS if isinstance(exc, type_)), status.HTTP_500_INTERNAL_SERVER_ERROR)
        if code >= status.HTTP_500_INTERNAL_SERVER_ERROR:
            journal.error("Erreur %s : %s", type(exc).__name__, exc)
        return JSONResponse(status_code=code, content={"detail": str(exc)})

    for module in (systeme, clients, appels, stock, labo):
        app.include_router(module.routeur)

    app.mount("/static", StaticFiles(directory=DOSSIER_STATIQUE), name="static")

    @app.get("/", include_in_schema=False)
    def page_accueil() -> FileResponse:
        return FileResponse(DOSSIER_STATIQUE / "index.html")

    return app
