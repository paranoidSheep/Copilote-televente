"""Fournisseur Claude, via le SDK officiel `anthropic`."""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass

import anthropic
from anthropic.types.beta import (
    BetaMessage,
    BetaMessageParam,
    BetaTextBlock,
    BetaToolParam,
    BetaToolResultBlockParam,
    BetaToolUseBlock,
)

from pydantic import JsonValue, TypeAdapter

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
    "tool_use": Arret.OUTILS,
    "end_turn": Arret.FIN,
    "stop_sequence": Arret.FIN,
    "pause_turn": Arret.FIN,
    "refusal": Arret.REFUS,
    "max_tokens": Arret.LIMITE,
    "model_context_window_exceeded": Arret.LIMITE,
}

# Bascule serveur en cas de refus : l'API rejoue la requête sur un autre modèle.
BETA_BASCULE_REFUS = "server-side-fallback-2026-07-01"


_ARGUMENTS = TypeAdapter(dict[str, JsonValue])


@dataclass(frozen=True, slots=True)
class ParametresClaude:
    modele: str
    effort: str = "medium"  # bon compromis qualité / latence pour un enchaînement d'outils
    max_tokens: int = 16000
    bascule_refus: bool = True


class FournisseurClaude:
    """Claude via l'API Anthropic (la clé est lue par le SDK dans ANTHROPIC_API_KEY)."""

    nom = "anthropic"

    def __init__(self, parametres: ParametresClaude, client: anthropic.Anthropic | None = None) -> None:
        self._parametres = parametres
        self._client = client

    @property
    def modele(self) -> str:
        return self._parametres.modele

    def ouvrir_session(
        self, systeme: str, outils: Sequence[DefinitionOutil], metadonnees: Mapping[str, str]
    ) -> SessionClaude:
        if self._client is None:
            try:
                self._client = anthropic.Anthropic()
            except anthropic.AnthropicError as exc:
                raise ErreurFournisseurLLM("clé d'API Anthropic absente ou invalide") from exc
        return SessionClaude(self._parametres, self._client, systeme, outils)


class SessionClaude:
    def __init__(
        self,
        parametres: ParametresClaude,
        client: anthropic.Anthropic,
        systeme: str,
        outils: Sequence[DefinitionOutil],
    ) -> None:
        self._parametres = parametres
        self._client = client
        self._systeme = systeme
        self._outils: list[BetaToolParam] = [
            {"name": o.nom, "description": o.description, "input_schema": o.schema_entree, "strict": True}  # type: ignore[typeddict-item]
            for o in outils
        ]
        self._messages: list[BetaMessageParam] = []

    def envoyer(self, message: MessageUtilisateur) -> ReponseLLM:
        if isinstance(message, str):
            self._messages.append({"role": "user", "content": message})
        else:
            resultats: list[BetaToolResultBlockParam] = [
                {"type": "tool_result", "tool_use_id": r.appel_id, "content": r.contenu, "is_error": r.est_erreur}
                for r in message
            ]
            self._messages.append({"role": "user", "content": resultats})

        reponse = self._appeler_api()
        # L'historique conserve le contenu complet (blocs de réflexion compris), comme l'exige l'API.
        self._messages.append({"role": "assistant", "content": reponse.content})
        return _traduire(reponse)

    def _appeler_api(self) -> BetaMessage:
        p = self._parametres
        options: dict[str, object] = {}
        if p.bascule_refus:
            options = {"betas": [BETA_BASCULE_REFUS], "fallbacks": "default"}
        try:
            return self._client.beta.messages.create(  # type: ignore[call-overload, no-any-return]
                model=p.modele,
                max_tokens=p.max_tokens,
                system=self._systeme,
                tools=self._outils,
                messages=self._messages,
                output_config={"effort": p.effort},
                **options,
            )
        except anthropic.APIConnectionError as exc:
            raise ErreurFournisseurLLM("service IA injoignable") from exc
        except anthropic.RateLimitError as exc:
            raise ErreurFournisseurLLM("limite d'utilisation de l'IA atteinte") from exc
        except anthropic.AuthenticationError as exc:
            raise ErreurFournisseurLLM("clé d'API Anthropic refusée") from exc
        except anthropic.APIStatusError as exc:
            raise ErreurFournisseurLLM(f"erreur du service IA ({exc.status_code})") from exc


def _traduire(reponse: BetaMessage) -> ReponseLLM:
    textes = [b.text for b in reponse.content if isinstance(b, BetaTextBlock)]
    appels = [
        AppelOutil(id=b.id, nom=b.name, arguments=_ARGUMENTS.validate_python(b.input))
        for b in reponse.content
        if isinstance(b, BetaToolUseBlock)
    ]
    return ReponseLLM(
        arret=_ARRETS.get(reponse.stop_reason, Arret.FIN),
        modele=reponse.model,
        textes=textes,
        appels=appels,
        usage=Usage(jetons_entree=reponse.usage.input_tokens, jetons_sortie=reponse.usage.output_tokens),
    )

