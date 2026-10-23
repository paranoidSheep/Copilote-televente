"""Application FastAPI : routeurs, sécurité, gestion des erreurs, interface web.

Lancement :
    python -m copilote                                    # http://localhost:8000
    uvicorn copilote.api.app:creer_app --factory --reload
"""

from __future__ import annotations

import logging
import time
from collections.abc import Awaitable, Callable
from pathlib import Path

from fastapi import Depends, FastAPI, Request, Response, status
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles

from copilote import __version__
from copilote.application import Application, creer_application
from copilote.comptes import (
    AuthentificationRefusee,
    MotDePasseInvalide,
    Permission,
    TropDeTentatives,
    UtilisateurExistant,
    UtilisateurIntrouvable,
)
from copilote.config import Config
from copilote.domaine import (
    ClientIntrouvable,
    ErreurConfiguration,
    ErreurCopilote,
    ErreurSourceDonnees,
    ProduitIntrouvable,
)
from copilote.services import ErreurValidation

from .dependances import exiger, utilisateur_courant
from .routes import admin, appels, auth, clients, labo, stock, systeme

DOSSIER_STATIQUE = Path(__file__).resolve().parent / "static"
journal = logging.getLogger("copilote.api")

# Traduction des erreurs métier en codes HTTP (du plus spécifique au plus général)
CODES_ERREURS: list[tuple[type[ErreurCopilote], int]] = [
    (TropDeTentatives, status.HTTP_429_TOO_MANY_REQUESTS),
    (AuthentificationRefusee, status.HTTP_401_UNAUTHORIZED),
    (UtilisateurExistant, status.HTTP_409_CONFLICT),
    (UtilisateurIntrouvable, status.HTTP_404_NOT_FOUND),
    (MotDePasseInvalide, status.HTTP_422_UNPROCESSABLE_CONTENT),
    (ClientIntrouvable, status.HTTP_404_NOT_FOUND),
    (ProduitIntrouvable, status.HTTP_404_NOT_FOUND),
    (ErreurValidation, status.HTTP_422_UNPROCESSABLE_CONTENT),
    (ErreurSourceDonnees, status.HTTP_502_BAD_GATEWAY),
    (ErreurConfiguration, status.HTTP_500_INTERNAL_SERVER_ERROR),
]

# En-têtes de sécurité ajoutés à toutes les réponses
EN_TETES_SECURITE = {
    "X-Content-Type-Options": "nosniff",
    "X-Frame-Options": "DENY",
    "Referrer-Policy": "same-origin",
    "Permissions-Policy": "camera=(), microphone=(), geolocation=()",
    # Scripts et styles servis uniquement par le copilote ; « unsafe-inline » pour les attributs style.
    "Content-Security-Policy": (
        "default-src 'self'; script-src 'self'; style-src 'self' 'unsafe-inline'; img-src 'self' data:; "
        "frame-ancestors 'none'; base-uri 'self'; form-action 'self'"
    ),
}

# La documentation interactive (/docs) charge ses ressources depuis un CDN : CSP adaptée.
CSP_DOCUMENTATION = (
    "default-src 'self'; script-src 'self' 'unsafe-inline' https://cdn.jsdelivr.net; "
    "style-src 'self' 'unsafe-inline' https://cdn.jsdelivr.net; img-src 'self' data: https://fastapi.tiangolo.com"
)

type Suivant = Callable[[Request], Awaitable[Response]]


def creer_app(application: Application | None = None) -> FastAPI:
    application = application or creer_application(Config.depuis_environnement())
    documentation = application.config.securite.documentation_api
    app = FastAPI(
        title="Copilote télévente",
        description=(
            "Fiches d'appel, file d'appels priorisée et plan d'écoulement du stock, "
            "à partir des données ERP (lecture seule)."
        ),
        version=__version__,
        docs_url="/docs" if documentation else None,
        redoc_url=None,
        openapi_url="/openapi.json" if documentation else None,
    )
    app.state.application = application

    @app.middleware("http")
    async def securite_et_journal(requete: Request, suivant: Suivant) -> Response:
        debut = time.perf_counter()
        # Les écritures n'acceptent que du JSON : un formulaire envoyé depuis un autre site est rejeté.
        if (
            requete.method in {"POST", "PUT", "PATCH", "DELETE"}
            and not requete.headers.get("content-type", "").startswith("application/json")
            and requete.url.path != "/auth/deconnexion"
        ):
            reponse: Response = JSONResponse(
                status_code=status.HTTP_415_UNSUPPORTED_MEDIA_TYPE, content={"detail": "JSON attendu."}
            )
        else:
            reponse = await suivant(requete)
        for nom, valeur in EN_TETES_SECURITE.items():
            reponse.headers.setdefault(nom, valeur)
        if requete.url.path in {"/docs", "/openapi.json"}:
            reponse.headers["Content-Security-Policy"] = CSP_DOCUMENTATION
        if not requete.url.path.startswith("/static") and requete.url.path != "/sante":  # sonde : pas de bruit
            utilisateur = getattr(requete.state, "utilisateur", None)
            journal.info(
                "%s %s → %s",
                requete.method,
                requete.url.path,
                reponse.status_code,
                extra={
                    "methode": requete.method,
                    "chemin": requete.url.path,
                    "statut": reponse.status_code,
                    "duree_ms": round((time.perf_counter() - debut) * 1000),
                    "utilisateur": utilisateur.identifiant if utilisateur else None,
                },
            )
        return reponse

    @app.exception_handler(ErreurCopilote)
    async def erreur_metier(_requete: Request, exc: ErreurCopilote) -> JSONResponse:
        code = next((c for type_, c in CODES_ERREURS if isinstance(exc, type_)), status.HTTP_500_INTERNAL_SERVER_ERROR)
        if code >= status.HTTP_500_INTERNAL_SERVER_ERROR:
            journal.error("Erreur %s : %s", type(exc).__name__, exc)
        return JSONResponse(status_code=code, content={"detail": str(exc)})

    # Routes publiques : sonde de santé, connexion, interface (page de connexion comprise)
    app.include_router(systeme.routeur)
    app.include_router(auth.routeur)
    # Routes réservées aux utilisateurs connectés
    authentifie = [Depends(utilisateur_courant)]
    for module in (clients, appels, stock):
        app.include_router(module.routeur, dependencies=authentifie)
    app.include_router(labo.routeur, dependencies=[Depends(exiger(Permission.UTILISER_LE_LABO))])
    app.include_router(admin.routeur, dependencies=[Depends(exiger(Permission.DIAGNOSTIQUER_LES_DONNEES))])

    app.mount("/static", StaticFiles(directory=DOSSIER_STATIQUE), name="static")

    @app.api_route("/", methods=["GET", "HEAD"], include_in_schema=False)
    def page_accueil() -> FileResponse:
        return FileResponse(DOSSIER_STATIQUE / "index.html")

    return app
