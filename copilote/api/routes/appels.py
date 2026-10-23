"""File d'appels, comptes-rendus et statistiques."""

from __future__ import annotations

from datetime import date
from typing import Annotated

from fastapi import APIRouter, HTTPException, Query, Response, status
from fastapi.responses import PlainTextResponse

from copilote.analyses import FileAppels, Journee
from copilote.api.dependances import ApplicationDep, UtilisateurDep
from copilote.api.schemas import CompteRenduEnregistre
from copilote.comptes import Permission
from copilote.journal import CompteRendu, SaisieCompteRendu, StatistiquesAppels

routeur = APIRouter(tags=["appels"])

JoursQuery = Annotated[int, Query(ge=1, le=366, description="Période analysée, en jours")]


@routeur.get("/appels/file", response_model=FileAppels)
def file_appels(app: ApplicationDep, utilisateur: UtilisateurDep, televendeur: str | None = None) -> FileAppels:
    """File du jour. Un télévendeur ne voit que ses clients ; un responsable peut filtrer librement."""
    if not utilisateur.peut(Permission.VOIR_TOUTES_LES_FILES):
        televendeur = utilisateur.nom_affiche
    return app.pilotage.file_appels(televendeur)


@routeur.get("/appels/journee", response_model=Journee)
def journee(app: ApplicationDep, utilisateur: UtilisateurDep, televendeur: str | None = None) -> Journee:
    """Ma journée : objectifs, agenda des rappels et avancement de la tournée."""
    if not utilisateur.peut(Permission.VOIR_TOUTES_LES_FILES):
        televendeur = utilisateur.nom_affiche
    return app.pilotage.journee(televendeur)


@routeur.get("/comptes-rendus/commandes.csv", response_class=Response)
def export_commandes(
    app: ApplicationDep,
    utilisateur: UtilisateurDep,
    jour: Annotated[date | None, Query(description="Jour exporté (AAAA-MM-JJ) ; aujourd'hui par défaut")] = None,
    televendeur: str | None = None,
) -> Response:
    """Produits acceptés du jour, en CSV (Excel), pour la saisie dans l'ERP.

    Un télévendeur n'exporte que ses propres comptes-rendus.
    """
    if not utilisateur.peut(Permission.VOIR_TOUTES_LES_FILES):
        televendeur = utilisateur.nom_affiche
    contenu = app.journal.export_commandes(jour, televendeur)
    nom = f"commandes-{(jour or app.referentiels.obtenir().date_du_jour):%Y-%m-%d}.csv"
    return Response(
        contenu.encode("utf-8"),
        media_type="text/csv; charset=utf-8",
        headers={"Content-Disposition": f'attachment; filename="{nom}"'},
    )


@routeur.post("/comptes-rendus", response_model=CompteRenduEnregistre, status_code=status.HTTP_201_CREATED)
def enregistrer_compte_rendu(
    saisie: SaisieCompteRendu, app: ApplicationDep, utilisateur: UtilisateurDep
) -> CompteRenduEnregistre:
    """Enregistre le compte-rendu d'un appel au nom de l'utilisateur connecté.

    Le compte-rendu va dans le journal LOCAL du copilote, jamais dans l'ERP.
    """
    compte_rendu = app.journal.enregistrer(saisie.par(utilisateur.nom_affiche))
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
def statistiques(app: ApplicationDep, utilisateur: UtilisateurDep, jours: JoursQuery = 30) -> StatistiquesAppels:
    """Indicateurs globaux pour un responsable ; ses propres résultats pour un télévendeur."""
    televendeur = None if utilisateur.peut(Permission.VOIR_STATISTIQUES_GLOBALES) else utilisateur.nom_affiche
    return app.journal.statistiques(jours, televendeur)
