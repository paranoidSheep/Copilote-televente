"""Clients, fiche d'appel et vue 360."""

from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Query
from fastapi.responses import PlainTextResponse

from copilote.analyses import DetailsProduit, analyser_habitudes, analyser_produit, resumer_appels
from copilote.api.dependances import ApplicationDep
from copilote.api.schemas import Client360
from copilote.config import ModeLLM
from copilote.domaine import Client
from copilote.fiche import Fiche

routeur = APIRouter(prefix="/clients", tags=["clients"])

ModeQuery = Annotated[ModeLLM | None, Query(description="Rédacteur à utiliser ; par défaut celui de la configuration")]
RegenererQuery = Annotated[bool, Query(description="Ignorer le cache et régénérer la fiche")]


@routeur.get("", response_model=list[Client])
def lister_clients(
    app: ApplicationDep,
    q: Annotated[str | None, Query(description="Recherche dans le nom, la ville, le contact")] = None,
    type: Annotated[str | None, Query(description="Type d'établissement")] = None,  # noqa: A002
    televendeur: str | None = None,
) -> list[Client]:
    clients = sorted(app.referentiels.obtenir().clients.values(), key=lambda c: c.nom)
    if q:
        recherche = q.casefold()
        clients = [c for c in clients if recherche in f"{c.nom} {c.ville} {c.contact} {c.type}".casefold()]
    if type:
        clients = [c for c in clients if c.type == type]
    if televendeur:
        clients = [c for c in clients if c.commercial == televendeur]
    return clients


@routeur.get("/{client_id}", response_model=Client360)
def client_360(client_id: str, app: ApplicationDep) -> Client360:
    ref = app.referentiels.obtenir()
    comptes_rendus = app.journal.lister(client_id=client_id)
    return Client360(
        client=ref.client(client_id),
        habitudes=analyser_habitudes(ref, client_id),
        appels=resumer_appels(comptes_rendus, client_id, ref.date_du_jour, ref.regles),
        comptes_rendus=comptes_rendus[:20],
    )


@routeur.get("/{client_id}/fiche", response_model=Fiche)
def fiche_client(
    client_id: str, app: ApplicationDep, mode: ModeQuery = None, regenerer: RegenererQuery = False
) -> Fiche:
    # Fonction synchrone : FastAPI l'exécute dans un thread, l'appel à l'IA ne bloque pas le serveur.
    return app.fiches.generer(client_id, mode, regenerer)


@routeur.get("/{client_id}/fiche.txt", response_class=PlainTextResponse)
def fiche_client_texte(client_id: str, app: ApplicationDep, mode: ModeQuery = None) -> str:
    return app.fiches.generer(client_id, mode).texte


@routeur.get("/{client_id}/produits/{code}", response_model=DetailsProduit)
def details_produit(client_id: str, code: str, app: ApplicationDep) -> DetailsProduit:
    return analyser_produit(app.referentiels.obtenir(), client_id, code)
