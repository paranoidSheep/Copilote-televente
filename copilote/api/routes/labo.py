"""Laboratoire : inspection de l'agent (outils, prompts, comparaison des rédacteurs).

Destiné aux équipes projet pour tester, déboguer et démontrer le fonctionnement
de l'IA. Aucune donnée n'est modifiée.
"""

from __future__ import annotations

import json
from typing import Annotated

from fastapi import APIRouter, Query, status
from fastapi.responses import PlainTextResponse
from pydantic import BaseModel, ConfigDict, JsonValue

from copilote.agent import creer_boite_outils, definition_soumission
from copilote.agent.llm import AppelOutil, DefinitionOutil
from copilote.agent.prompts import SYSTEME, demande_fiche
from copilote.api.dependances import ApplicationDep
from copilote.config import ModeLLM
from copilote.evaluation import Campagne, DemandeEvaluation, ResumeCampagne, SuiviEvaluation, en_markdown
from copilote.fiche import Fiche

routeur = APIRouter(prefix="/labo", tags=["laboratoire"])


class ResultatOutilLabo(BaseModel):
    model_config = ConfigDict(frozen=True, json_schema_serialization_defaults_required=True)
    nom: str
    arguments: dict[str, JsonValue]
    est_erreur: bool
    resultat: JsonValue


class ConfigurationAgent(BaseModel):
    model_config = ConfigDict(frozen=True, json_schema_serialization_defaults_required=True)
    prompt_systeme: str
    exemple_demande: str
    outils: list[DefinitionOutil]


@routeur.get("/agent", response_model=ConfigurationAgent)
def configuration_agent(app: ApplicationDep, client_id: str = "C001") -> ConfigurationAgent:
    """Prompt système et outils (avec leurs schémas JSON) tels qu'envoyés au LLM."""
    ref = app.referentiels.obtenir()
    boite = creer_boite_outils(ref, client_id, [])
    return ConfigurationAgent(
        prompt_systeme=SYSTEME,
        exemple_demande=demande_fiche(ref.client(client_id), ref.date_du_jour),
        outils=[*boite.definitions(), definition_soumission()],
    )


@routeur.get("/clients/{client_id}/outils", response_model=list[ResultatOutilLabo])
def executer_outils(
    client_id: str,
    app: ApplicationDep,
    produit: Annotated[str | None, Query(description="Code produit pour l'outil details_produit")] = None,
) -> list[ResultatOutilLabo]:
    """Exécute chaque outil comme le ferait l'IA, et renvoie les résultats bruts."""
    ref = app.referentiels.obtenir()
    boite = creer_boite_outils(ref, client_id, app.journal.lister(client_id=client_id))
    resultats = []
    for nom in boite.noms:
        arguments: dict[str, JsonValue] = {"client_id": client_id}
        if nom == "details_produit":
            if produit is None:
                continue
            arguments["code"] = produit
        sortie = boite.executer(AppelOutil(id=f"labo_{nom}", nom=nom, arguments=arguments))
        contenu: JsonValue = sortie.contenu if sortie.est_erreur else json.loads(sortie.contenu)
        resultats.append(
            ResultatOutilLabo(nom=nom, arguments=arguments, est_erreur=sortie.est_erreur, resultat=contenu)
        )
    return resultats


@routeur.get("/clients/{client_id}/comparaison", response_model=dict[ModeLLM, Fiche])
def comparer_redacteurs(client_id: str, app: ApplicationDep) -> dict[ModeLLM, Fiche]:
    """Génère la fiche avec chaque rédacteur disponible (hors cache : les fiches servies ne changent pas)."""
    app.referentiels.obtenir().client(client_id)  # lève ClientIntrouvable
    return {mode: app.fiches.produire(client_id, mode).fiche for mode in app.fiches.modes_disponibles}


# ---------------------------------------------------------------------------------
# Banc d'évaluation de la qualité des fiches
# ---------------------------------------------------------------------------------


@routeur.get("/evaluations", response_model=list[ResumeCampagne])
def historique_evaluations(
    app: ApplicationDep, limite: Annotated[int, Query(ge=1, le=100)] = 20
) -> list[ResumeCampagne]:
    """Campagnes d'évaluation passées, les plus récentes d'abord."""
    return app.evaluation.lister(limite)


@routeur.get("/evaluations/suivi", response_model=SuiviEvaluation | None)
def suivi_evaluation(app: ApplicationDep) -> SuiviEvaluation | None:
    """Avancement de la dernière campagne lancée depuis l'interface (null si aucune)."""
    return app.evaluation.suivi()


@routeur.post("/evaluations", response_model=SuiviEvaluation, status_code=status.HTTP_202_ACCEPTED)
def lancer_evaluation(demande: DemandeEvaluation, app: ApplicationDep) -> SuiviEvaluation:
    """Lance une campagne en arrière-plan ; 409 si une campagne est déjà en cours."""
    return app.evaluation.lancer(demande.redacteurs, demande.clients)


@routeur.get("/evaluations/{campagne_id}", response_model=Campagne)
def detail_evaluation(campagne_id: int, app: ApplicationDep) -> Campagne:
    return app.evaluation.obtenir(campagne_id)


@routeur.get("/evaluations/{campagne_id}/rapport.md", response_class=PlainTextResponse)
def rapport_evaluation(campagne_id: int, app: ApplicationDep) -> PlainTextResponse:
    """Rapport Markdown de la campagne, à joindre à une revue de code ou à un courriel."""
    nom = f"evaluation-{campagne_id}.md"
    return PlainTextResponse(
        en_markdown(app.evaluation.obtenir(campagne_id)),
        media_type="text/markdown; charset=utf-8",
        headers={"Content-Disposition": f'attachment; filename="{nom}"'},
    )
