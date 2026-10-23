"""File d'appels, comptes-rendus et statistiques."""

from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, HTTPException, Query, status
from fastapi.responses import PlainTextResponse

from copilote.analyses import FileAppels
from copilote.api.dependances import ApplicationDep
from copilote.api.schemas import CompteRenduEnregistre
from copilote.journal import CompteRendu, NouveauCompteRendu, StatistiquesAppels

routeur = APIRouter(tags=["appels"])

JoursQuery = Annotated[int, Query(ge=1, le=366, description="Période analysée, en jours")]


@routeur.get("/appels/file", response_model=FileAppels)
def file_appels(app: ApplicationDep, televendeur: str | None = None) -> FileAppels:
    return app.pilotage.file_appels(televendeur)


@routeur.post("/comptes-rendus", response_model=CompteRenduEnregistre, status_code=status.HTTP_201_CREATED)
def enregistrer_compte_rendu(nouveau: NouveauCompteRendu, app: ApplicationDep) -> CompteRenduEnregistre:
    """Enregistre le compte-rendu d'un appel (dans le journal LOCAL du copilote, jamais dans l'ERP)."""
    compte_rendu = app.journal.enregistrer(nouveau)
    return CompteRenduEnregistre(compte_rendu=compte_rendu, texte_saisie_erp=app.journal.texte_saisie_erp(compte_rendu))


@routeur.get("/comptes-rendus", response_model=list[CompteRendu])
def lister_comptes_rendus(
    app: ApplicationDep, client_id: str | None = None, jours: JoursQuery = 30
) -> list[CompteRendu]:
    return app.journal.lister(client_id=client_id, jours=jours)


@routeur.get("/comptes-rendus/{compte_rendu_id}/saisie-erp", response_class=PlainTextResponse)
def texte_saisie_erp(compte_rendu_id: int, app: ApplicationDep) -> str:
    compte_rendu = app.journal.obtenir(compte_rendu_id)
    if compte_rendu is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, f"Compte-rendu inconnu : {compte_rendu_id}")
    return app.journal.texte_saisie_erp(compte_rendu)


@routeur.get("/statistiques", response_model=StatistiquesAppels)
def statistiques(app: ApplicationDep, jours: JoursQuery = 30) -> StatistiquesAppels:
    return app.journal.statistiques(jours)
