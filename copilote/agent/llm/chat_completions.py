"""Fournisseurs « Chat Completions » : OpenAI, Mistral, Gemini, Ollama, vLLM…, via le SDK officiel `openai`.

Tous ces services exposent l'API Chat Completions d'OpenAI avec appel d'outils
(« function calling »). Seuls changent l'adresse, la clé et le nom du modèle :
un seul adaptateur suffit, configuré par le catalogue (`copilote.fournisseurs`).

Traduction vers le contrat de l'agent :
- le prompt système devient un message `system`, les résultats d'outils des
  messages `tool` (un par appel, rattaché par `tool_call_id`) ;
- les arguments d'outils arrivent en JSON texte : un JSON invalide est transmis
  tel quel à la boîte à outils, qui le refuse et l'explique au modèle ;
- le message de l'assistant est renvoyé tel quel dans l'historique, appels
  d'outils compris (certains fournisseurs y ajoutent des champs à conserver).
"""

from __future__ import annotations

import json
from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field

import openai
from openai.types.chat import (
    ChatCompletion,
    ChatCompletionFunctionToolParam,
    ChatCompletionMessage,
    ChatCompletionMessageFunctionToolCall,
    ChatCompletionMessageParam,
)
from pydantic import JsonValue, TypeAdapter, ValidationError

from .types import (
    AppelOutil,
    Arret,
    DefinitionOutil,
    ErreurFournisseurLLM,
    MessageUtilisateur,
    ReponseLLM,
    Usage,
)

_ARRETS: dict[str | None, Arret] = {
    "tool_calls": Arret.OUTILS,
    "function_call": Arret.OUTILS,
    "stop": Arret.FIN,
    "length": Arret.LIMITE,
    "content_filter": Arret.REFUS,
}
_ARGUMENTS = TypeAdapter(dict[str, JsonValue])
CLE_ABSENTE = "aucune-cle"  # le SDK exige une clé ; un serveur local l'ignore
CLE_ARGUMENTS_INVALIDES = "arguments_json_invalides"
PREFIXE_ERREUR_OUTIL = "Erreur : "  # l'API n'a pas de champ « erreur » pour un résultat d'outil
MAX_JETONS_SORTIE = 8192  # largement assez pour une fiche, sans dépasser le contexte d'un petit modèle local


@dataclass(frozen=True, slots=True)
class ParametresChatCompletions:
    nom: str  # identifiant court du fournisseur : « mistral », « openai »… (trace, journaux)
    libelle: str  # « Mistral AI » : dans les messages d'erreur affichés au télévendeur
    modele: str
    cle_api: str | None = field(default=None, repr=False)
    url: str | None = None  # None : adresse de l'API OpenAI
    limite_jetons: str = "max_tokens"  # ou « max_completion_tokens » (API OpenAI)
    max_jetons_sortie: int = MAX_JETONS_SORTIE
    outils_stricts: bool = False
    delai_secondes: float = 120.0


class FournisseurChatCompletions:
    def __init__(self, parametres: ParametresChatCompletions, client: openai.OpenAI | None = None) -> None:
        self._parametres = parametres
        self._client = client

    @property
    def nom(self) -> str:
        return self._parametres.nom

    @property
    def modele(self) -> str:
        return self._parametres.modele

    def ouvrir_session(
        self, systeme: str, outils: Sequence[DefinitionOutil], metadonnees: Mapping[str, str]
    ) -> SessionChatCompletions:
        if self._client is None:
            p = self._parametres
            self._client = openai.OpenAI(
                api_key=p.cle_api or CLE_ABSENTE, base_url=p.url, timeout=p.delai_secondes, max_retries=2
            )
        return SessionChatCompletions(self._parametres, self._client, systeme, outils)


class SessionChatCompletions:
    def __init__(
        self,
        parametres: ParametresChatCompletions,
        client: openai.OpenAI,
        systeme: str,
        outils: Sequence[DefinitionOutil],
    ) -> None:
        self._parametres = parametres
        self._client = client
        self._outils: list[ChatCompletionFunctionToolParam] = [_outil(o, parametres.outils_stricts) for o in outils]
        self._messages: list[ChatCompletionMessageParam] = [{"role": "system", "content": systeme}]

    def envoyer(self, message: MessageUtilisateur) -> ReponseLLM:
        if isinstance(message, str):
            self._messages.append({"role": "user", "content": message})
        else:
            for resultat in message:
                contenu = f"{PREFIXE_ERREUR_OUTIL}{resultat.contenu}" if resultat.est_erreur else resultat.contenu
                self._messages.append({"role": "tool", "tool_call_id": resultat.appel_id, "content": contenu})

        reponse = self._appeler_api()
        if not reponse.choices:
            raise ErreurFournisseurLLM(f"réponse vide de {self._parametres.libelle}")
        choix = reponse.choices[0]
        self._messages.append(_message_assistant(choix.message))
        return _traduire(reponse, choix.message, choix.finish_reason, self._parametres.modele)

    def _appeler_api(self) -> ChatCompletion:
        p = self._parametres
        limite = {p.limite_jetons: p.max_jetons_sortie}
        try:
            return self._client.chat.completions.create(  # type: ignore[call-overload, no-any-return]
                model=p.modele,
                messages=self._messages,
                tools=self._outils,
                tool_choice="auto",
                **limite,
            )
        except openai.APITimeoutError as exc:
            raise ErreurFournisseurLLM(f"{p.libelle} ne répond pas (délai dépassé)") from exc
        except openai.APIConnectionError as exc:
            raise ErreurFournisseurLLM(f"{p.libelle} injoignable") from exc
        except (openai.AuthenticationError, openai.PermissionDeniedError) as exc:
            raise ErreurFournisseurLLM(f"clé d'API {p.libelle} refusée") from exc
        except openai.NotFoundError as exc:
            raise ErreurFournisseurLLM(f"modèle « {p.modele} » introuvable chez {p.libelle}") from exc
        except openai.RateLimitError as exc:
            raise ErreurFournisseurLLM(f"limite d'utilisation de {p.libelle} atteinte") from exc
        except openai.BadRequestError as exc:
            detail = _detail(exc)
            if "api key" in detail.lower():  # Gemini signale une clé invalide par un 400, pas un 401
                raise ErreurFournisseurLLM(f"clé d'API {p.libelle} refusée") from exc
            raise ErreurFournisseurLLM(f"requête refusée par {p.libelle} : {detail}") from exc
        except openai.APIStatusError as exc:
            raise ErreurFournisseurLLM(f"erreur de {p.libelle} ({exc.status_code})") from exc


def _outil(definition: DefinitionOutil, stricts: bool) -> ChatCompletionFunctionToolParam:
    fonction: dict[str, object] = {
        "name": definition.nom,
        "description": definition.description,
        "parameters": definition.schema_entree,
    }
    if stricts:  # pas toujours accepté hors de l'API OpenAI : désactivé par défaut
        fonction["strict"] = True
    return {"type": "function", "function": fonction}  # type: ignore[typeddict-item]


def _message_assistant(message: ChatCompletionMessage) -> ChatCompletionMessageParam:
    """Le message de l'assistant pour l'historique, appels d'outils compris et intacts.

    Les appels d'outils sont recopiés avec tous leurs champs : Gemini, par exemple,
    y joint une signature de raisonnement qu'il exige au tour suivant.
    """
    assistant: dict[str, object] = {"role": "assistant", "content": message.content or ""}
    if message.tool_calls:
        assistant["tool_calls"] = [appel.model_dump(exclude_none=True) for appel in message.tool_calls]
    return assistant  # type: ignore[return-value]


def _arguments(texte: str) -> dict[str, JsonValue]:
    if not texte.strip():
        return {}
    try:
        return _ARGUMENTS.validate_python(json.loads(texte))
    except (json.JSONDecodeError, ValidationError):
        # La boîte à outils refusera cet argument inconnu et l'expliquera au modèle, qui pourra corriger.
        return {CLE_ARGUMENTS_INVALIDES: texte[:500]}


def _traduire(reponse: ChatCompletion, message: ChatCompletionMessage, fin: str | None, modele: str) -> ReponseLLM:
    appels = [
        AppelOutil(id=a.id, nom=a.function.name, arguments=_arguments(a.function.arguments))
        for a in message.tool_calls or []
        if isinstance(a, ChatCompletionMessageFunctionToolCall)
    ]
    arret = _ARRETS.get(fin, Arret.FIN)
    if message.refusal:
        arret = Arret.REFUS
    elif appels and arret is Arret.FIN:  # certains serveurs répondent « stop » avec des appels d'outils
        arret = Arret.OUTILS
    usage = reponse.usage
    return ReponseLLM(
        arret=arret,
        modele=reponse.model or modele,
        textes=[message.content] if message.content else [],
        appels=appels,
        usage=Usage(
            jetons_entree=usage.prompt_tokens if usage else 0, jetons_sortie=usage.completion_tokens if usage else 0
        ),
    )


def _detail(exc: openai.APIStatusError) -> str:
    """Message d'erreur du fournisseur, quelle que soit la forme du corps.

    Formes rencontrées : `{"message": …}`, `{"error": {"message": …}}` et, chez Gemini,
    `[{"error": {"message": …}}]`.
    """
    corps: object = exc.body
    if isinstance(corps, list) and corps:
        corps = corps[0]
    if isinstance(corps, dict):
        corps = corps.get("error", corps)
    if isinstance(corps, dict) and isinstance(message := corps.get("message"), str):
        return message[:200]
    return str(exc.message)[:200]
