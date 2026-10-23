"""Connexion et déconnexion (session par cookie signé)."""

from __future__ import annotations

from fastapi import APIRouter, Response, status

from copilote.api.dependances import NOM_COOKIE, ApplicationDep
from copilote.api.schemas import Identifiants
from copilote.comptes import Utilisateur

routeur = APIRouter(prefix="/auth", tags=["authentification"])


@routeur.post("/connexion", response_model=Utilisateur)
def connexion(identifiants: Identifiants, reponse: Response, app: ApplicationDep) -> Utilisateur:
    utilisateur, jeton = app.comptes.connecter(identifiants.identifiant, identifiants.mot_de_passe)
    reponse.set_cookie(
        NOM_COOKIE,
        jeton,
        max_age=app.comptes.duree_session_secondes,
        httponly=True,  # inaccessible au JavaScript
        secure=app.config.securite.cookie_securise,  # HTTPS uniquement en production
        samesite="strict",  # jamais envoyé depuis un autre site (protection CSRF)
        path="/",
    )
    return utilisateur


@routeur.post("/deconnexion", status_code=status.HTTP_204_NO_CONTENT)
def deconnexion(reponse: Response, app: ApplicationDep) -> None:
    reponse.delete_cookie(NOM_COOKIE, path="/", secure=app.config.securite.cookie_securise, samesite="strict")
