"""Construction des fournisseurs de LLM à partir de leur configuration."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import replace

from copilote.fournisseurs import ConfigFournisseur, ModeLLM, Protocole

from .chat_completions import MAX_JETONS_SORTIE, FournisseurChatCompletions, ParametresChatCompletions
from .claude import FournisseurClaude, ParametresClaude
from .types import FournisseurLLM


def creer_fournisseur(config: ConfigFournisseur) -> FournisseurLLM:
    """Le client du fournisseur configuré (la configuration doit être complète)."""
    if not config.utilisable or config.modele is None:
        raise ValueError(f"{config.libelle} : configuration incomplète ({', '.join(config.manquants)})")
    profil = config.profil
    if profil.protocole is Protocole.ANTHROPIC:
        parametres = ParametresClaude(modele=config.modele, cle_api=config.cle_api)
        if config.max_jetons_sortie:
            parametres = replace(parametres, max_tokens=config.max_jetons_sortie)
        return FournisseurClaude(parametres)
    return FournisseurChatCompletions(
        ParametresChatCompletions(
            nom=profil.mode.value,
            libelle=config.libelle,
            modele=config.modele,
            cle_api=config.cle_api,
            url=config.url,
            limite_jetons=profil.limite_jetons,
            max_jetons_sortie=config.max_jetons_sortie or MAX_JETONS_SORTIE,
            outils_stricts=config.outils_stricts,
        )
    )


def creer_fournisseurs(configs: Mapping[ModeLLM, ConfigFournisseur]) -> dict[ModeLLM, FournisseurLLM]:
    """Tous les fournisseurs entièrement configurés."""
    return {mode: creer_fournisseur(c) for mode, c in configs.items() if c.utilisable}
