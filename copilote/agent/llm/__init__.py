"""Fournisseurs de LLM interchangeables derrière un contrat commun."""

from .chat_completions import FournisseurChatCompletions, ParametresChatCompletions
from .claude import FournisseurClaude, ParametresClaude
from .fabrique import creer_fournisseur, creer_fournisseurs
from .simule import DOSSIER_CASSETTES, Cassette, FournisseurSimule, charger_cassette
from .types import (
    AppelOutil,
    Arret,
    DefinitionOutil,
    ErreurFournisseurLLM,
    FournisseurLLM,
    MessageUtilisateur,
    ReponseLLM,
    ResultatOutil,
    SessionLLM,
    Usage,
)

__all__ = [
    "DOSSIER_CASSETTES",
    "AppelOutil",
    "Arret",
    "Cassette",
    "DefinitionOutil",
    "ErreurFournisseurLLM",
    "FournisseurChatCompletions",
    "FournisseurClaude",
    "FournisseurLLM",
    "FournisseurSimule",
    "MessageUtilisateur",
    "ParametresChatCompletions",
    "ParametresClaude",
    "ReponseLLM",
    "ResultatOutil",
    "SessionLLM",
    "Usage",
    "charger_cassette",
    "creer_fournisseur",
    "creer_fournisseurs",
]
