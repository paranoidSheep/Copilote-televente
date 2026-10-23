"""Fournisseurs de LLM interchangeables derrière un contrat commun."""

from .claude import FournisseurClaude, ParametresClaude
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
    "FournisseurClaude",
    "FournisseurLLM",
    "FournisseurSimule",
    "MessageUtilisateur",
    "ParametresClaude",
    "ReponseLLM",
    "ResultatOutil",
    "SessionLLM",
    "Usage",
    "charger_cassette",
]
