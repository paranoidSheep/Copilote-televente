"""Laboratoire : inspection de l'agent (outils, prompts, comparaison des rédacteurs).

Destiné aux équipes projet pour tester, déboguer et démontrer le fonctionnement
de l'IA. Aucune donnée n'est modifiée.
"""

from __future__ import annotations

import json
from typing import Annotated

from fastapi import APIRouter, Query
from pydantic import BaseModel, ConfigDict, JsonValue

from copilote.agent import creer_boite_outils, definition_soumission
from copilote.agent.llm import AppelOutil, DefinitionOutil
from copilote.agent.prompts import SYSTEME, demande_fiche
from copilote.api.dependances import ApplicationDep
from copilote.config import ModeLLM
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
    """Génère la fiche avec chaque rédacteur disponible (nouvelle génération à chaque appel)."""
    return {mode: app.fiches.generer(client_id, mode, regenerer=True) for mode in app.fiches.modes_disponibles}
