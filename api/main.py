"""API web du copilote télévente.

Endpoints :
- GET /                     page web (liste des clients puis fiche d'appel)
- GET /clients              liste des clients
- GET /clients/{id}/fiche   fiche d'appel générée (JSON, avec sa version texte)
- GET /sante                état du service (source de données, IA active ou mode repli)

Lancement : `uvicorn api.main:app --reload` puis http://localhost:8000
"""

from __future__ import annotations

import logging
import threading
from datetime import date
from functools import lru_cache
from pathlib import Path

from fastapi import FastAPI, HTTPException, Query
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

from agent import Fiche, generer_fiche, ia_disponible
from agent.agent import modele_configure
from datahub import ClientIntrouvable, DataSource, DataSourceError, get_datasource

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s : %(message)s")

DOSSIER_STATIQUE = Path(__file__).resolve().parent / "static"

app = FastAPI(
    title="Copilote télévente",
    description="Prépare une fiche d'appel pour chaque client avant l'appel du télévendeur.",
    version="0.1.0",
)
app.mount("/static", StaticFiles(directory=DOSSIER_STATIQUE), name="static")


@lru_cache(maxsize=1)
def source_de_donnees() -> DataSource:
    """Source de données unique pour l'application (choisie par DATASOURCE)."""
    return get_datasource()


# Cache mémoire des fiches : une fiche par client et par jour, régénérable à la demande.
# Évite de rappeler l'IA à chaque ouverture de la même fiche.
_cache_fiches: dict[tuple[str, date], Fiche] = {}
_verrou_cache = threading.Lock()


class ResumeClient(BaseModel):
    id: str
    nom: str
    type: str
    ville: str
    contact: str
    telephone: str
    commercial: str


@app.get("/", include_in_schema=False)
def page_accueil() -> FileResponse:
    return FileResponse(DOSSIER_STATIQUE / "index.html")


@app.get("/sante")
def sante() -> dict:
    source = source_de_donnees()
    return {
        "statut": "ok",
        "source_donnees": source.nom,
        "date_du_jour": source.date_du_jour().isoformat(),
        "mode": "ia" if ia_disponible() else "repli",
        "modele": modele_configure() if ia_disponible() else None,
    }


@app.get("/clients", response_model=list[ResumeClient])
def liste_clients() -> list[ResumeClient]:
    try:
        clients = source_de_donnees().get_clients()
    except DataSourceError as exc:
        raise HTTPException(status_code=502, detail=str(exc)) from exc
    return [ResumeClient(**c.model_dump()) for c in sorted(clients, key=lambda c: c.nom)]


@app.get("/clients/{client_id}/fiche", response_model=Fiche)
def fiche_client(
    client_id: str,
    regenerer: bool = Query(False, description="Ignorer le cache et régénérer la fiche"),
) -> Fiche:
    # Fonction synchrone : FastAPI l'exécute dans un thread, l'appel à l'IA ne bloque pas le serveur.
    source = source_de_donnees()
    cle = (client_id, source.date_du_jour())
    if not regenerer and (fiche := _cache_fiches.get(cle)) is not None:
        return fiche
    try:
        fiche = generer_fiche(source, client_id)
    except ClientIntrouvable as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except DataSourceError as exc:
        raise HTTPException(status_code=502, detail=f"Source de données indisponible : {exc}") from exc
    with _verrou_cache:
        _cache_fiches[cle] = fiche
    return fiche
