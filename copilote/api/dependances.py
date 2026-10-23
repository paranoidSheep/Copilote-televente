"""Injection de dépendances : application, utilisateur connecté et contrôle des droits."""

from __future__ import annotations

from collections.abc import Callable
from datetime import datetime
from typing import Annotated, cast

from fastapi import Depends, HTTPException, Request, status

from copilote.application import Application
from copilote.comptes import Permission, Role, Utilisateur

NOM_COOKIE = "copilote_session"

# Sans authentification (poste de développement uniquement), chaque requête agit sous ce compte.
UTILISATEUR_DEVELOPPEMENT = Utilisateur(
    identifiant="developpement",
    nom_affiche="Poste de développement",
    role=Role.ADMIN,
    cree_le=datetime(2026, 1, 1),
)


def obtenir_application(request: Request) -> Application:
    return cast(Application, request.app.state.application)


ApplicationDep = Annotated[Application, Depends(obtenir_application)]


def utilisateur_courant(request: Request, app: ApplicationDep) -> Utilisateur:
    """Utilisateur authentifié par son cookie de session, sinon erreur 401."""
    if not app.config.securite.authentification:
        utilisateur = UTILISATEUR_DEVELOPPEMENT
    else:
        jeton = request.cookies.get(NOM_COOKIE)
        trouve = app.comptes.utilisateur_de_session(jeton) if jeton else None
        if trouve is None:
            raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Authentification requise.")
        utilisateur = trouve
    request.state.utilisateur = utilisateur  # pour les journaux d'accès
    return utilisateur


UtilisateurDep = Annotated[Utilisateur, Depends(utilisateur_courant)]


def exiger(permission: Permission) -> Callable[[Utilisateur], Utilisateur]:
    """Dépendance qui refuse l'accès (403) aux utilisateurs sans la permission."""

    def controle(utilisateur: UtilisateurDep) -> Utilisateur:
        if not utilisateur.peut(permission):
            raise HTTPException(status.HTTP_403_FORBIDDEN, "Accès réservé aux responsables.")
        return utilisateur

    return controle
