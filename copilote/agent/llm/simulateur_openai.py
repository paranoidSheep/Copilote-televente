"""Simulateur d'un service compatible OpenAI : les rédactions de l'IA simulée, servies au format Chat Completions.

Il sert à éprouver le branchement d'un fournisseur « compatible OpenAI » (Mistral,
Gemini, Ollama, vLLM…) de bout en bout, sans clé ni modèle : SDK `openai`, réseau,
appels d'outils, résultats renvoyés, soumission de la fiche, puis affichage dans
la fiche, le labo et le banc d'évaluation. Comme une vraie API, il refuse une
conversation où un appel d'outil n'a pas reçu son résultat.

    python -m copilote.agent.llm.simulateur_openai --port 8200 [--latence-ms 400]
    LLM_MODE=compatible LLM_COMPATIBLE_BASE_URL=http://127.0.0.1:8200/v1 \\
        LLM_COMPATIBLE_MODEL=cassettes LLM_COMPATIBLE_NOM="Simulateur OpenAI" python -m copilote

Le simulateur n'a pas d'état : chaque requête porte toute la conversation. Il
retrouve le client dans la demande initiale, puis rejoue la conversation avec
l'IA simulée pour produire la réponse du tour en cours.
"""

from __future__ import annotations

import argparse
import json
import re
import time
from collections.abc import Iterator, Sequence
from typing import Literal

from fastapi import FastAPI, Header
from fastapi.responses import JSONResponse
from pydantic import BaseModel, ConfigDict, JsonValue

from .chat_completions import PREFIXE_ERREUR_OUTIL
from .simule import DOSSIER_CASSETTES, FournisseurSimule
from .types import DefinitionOutil, ErreurFournisseurLLM, MessageUtilisateur, ReponseLLM, ResultatOutil

# La demande initiale de l'agent (`prompts.demande_fiche`) : « Prépare la fiche d'appel du client C005 : … »
_CLIENT = re.compile(r"du client (\S+) :")


class _Recu(BaseModel):
    model_config = ConfigDict(frozen=True, extra="ignore")  # un vrai service ignore les champs qu'il ne connaît pas


class MessageRecu(_Recu):
    role: Literal["system", "developer", "user", "assistant", "tool"]
    content: str | None = None
    tool_call_id: str | None = None


class FonctionDeclaree(_Recu):
    name: str
    description: str = ""
    parameters: dict[str, JsonValue] = {}


class OutilDeclare(_Recu):
    type: Literal["function"]
    function: FonctionDeclaree


class RequeteChat(_Recu):
    model: str
    messages: list[MessageRecu]
    tools: list[OutilDeclare] = []


def _tours(messages: Sequence[MessageRecu]) -> Iterator[MessageUtilisateur]:
    """Les envois successifs de l'agent : un message utilisateur, ou les résultats d'outils d'un même tour."""
    resultats: list[ResultatOutil] = []
    for message in messages:
        if message.role == "tool":
            contenu = message.content or ""
            resultats.append(
                ResultatOutil(
                    appel_id=message.tool_call_id or "",
                    contenu=contenu.removeprefix(PREFIXE_ERREUR_OUTIL),
                    est_erreur=contenu.startswith(PREFIXE_ERREUR_OUTIL),
                )
            )
            continue
        if resultats:
            yield resultats
            resultats = []
        if message.role == "user":
            yield message.content or ""
    if resultats:
        yield resultats


def repondre(requete: RequeteChat, simule: FournisseurSimule) -> ReponseLLM:
    """Rejoue la conversation reçue avec l'IA simulée ; renvoie la réponse au dernier envoi."""
    systeme = next((m.content or "" for m in requete.messages if m.role in {"system", "developer"}), "")
    demande = next((m.content or "" for m in requete.messages if m.role == "user"), "")
    if (trouve := _CLIENT.search(demande)) is None:
        raise ErreurFournisseurLLM("demande initiale sans identifiant client")
    outils = [
        DefinitionOutil(nom=o.function.name, description=o.function.description, schema_entree=o.function.parameters)
        for o in requete.tools
    ]
    session = simule.ouvrir_session(systeme, outils, {"client_id": trouve.group(1)})
    reponse: ReponseLLM | None = None
    for envoi in _tours(requete.messages):
        reponse = session.envoyer(envoi)  # mêmes envois, même cassette : mêmes réponses à chaque requête
    if reponse is None:
        raise ErreurFournisseurLLM("conversation sans message utilisateur")
    return reponse


def completion(reponse: ReponseLLM, modele: str) -> dict[str, JsonValue]:
    """Réponse au format Chat Completions."""
    appels: list[JsonValue] = [
        {
            "id": a.id,
            "type": "function",
            "function": {"name": a.nom, "arguments": json.dumps(a.arguments, ensure_ascii=False)},
        }
        for a in reponse.appels
    ]
    message: dict[str, JsonValue] = {"role": "assistant", "content": "\n".join(reponse.textes) or None}
    if appels:
        message["tool_calls"] = appels
    entree, sortie = reponse.usage.jetons_entree, reponse.usage.jetons_sortie
    return {
        "id": f"chatcmpl-{time.time_ns()}",
        "object": "chat.completion",
        "created": int(time.time()),
        "model": modele,
        "choices": [{"index": 0, "message": message, "finish_reason": "tool_calls" if appels else "stop"}],
        "usage": {"prompt_tokens": entree, "completion_tokens": sortie, "total_tokens": entree + sortie},
    }


def _erreur(statut: int, message: str) -> JSONResponse:
    return JSONResponse({"error": {"message": message, "type": "invalid_request_error"}}, status_code=statut)


def creer_simulateur_openai(cle: str | None = None, latence_ms: int = 0) -> FastAPI:
    """Application ASGI ; `cle` : clé d'API exigée (aucune par défaut, comme un serveur Ollama)."""
    simule = FournisseurSimule(DOSSIER_CASSETTES)
    app = FastAPI(title="Simulateur compatible OpenAI (copilote télévente)", version="1.0")

    @app.post("/v1/chat/completions", response_model=None)
    def chat_completions(requete: RequeteChat, authorization: str | None = Header(default=None)) -> JSONResponse:
        if cle is not None and authorization != f"Bearer {cle}":
            return _erreur(401, "Clé d'API invalide.")
        if latence_ms:
            time.sleep(latence_ms / 1000)
        try:
            reponse = repondre(requete, simule)
        except ErreurFournisseurLLM as exc:
            return _erreur(400, exc.raison)
        return JSONResponse(completion(reponse, requete.model))

    @app.get("/v1/models")
    def modeles() -> dict[str, JsonValue]:
        return {"object": "list", "data": [{"id": "cassettes", "object": "model", "owned_by": "copilote"}]}

    return app


def main() -> None:
    import uvicorn

    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--hote", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=8200)
    parser.add_argument("--cle", help="clé d'API exigée (aucune par défaut)")
    parser.add_argument("--latence-ms", type=int, default=0, help="latence ajoutée à chaque réponse")
    args = parser.parse_args()
    uvicorn.run(creer_simulateur_openai(cle=args.cle, latence_ms=args.latence_ms), host=args.hote, port=args.port)


if __name__ == "__main__":
    main()
