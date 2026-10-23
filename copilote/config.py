"""Configuration de l'application, lue une seule fois depuis l'environnement.

Toute la configuration passe par l'objet `Config` (immuable et typé) : aucun
autre module ne lit `os.environ` directement. Les tests construisent leur
propre `Config` sans toucher à l'environnement.
"""

from __future__ import annotations

import os
from collections.abc import Mapping
from dataclasses import dataclass
from enum import StrEnum
from pathlib import Path

from copilote.domaine import ErreurConfiguration

RACINE_PROJET = Path(__file__).resolve().parent.parent
MODELE_ANTHROPIC_PAR_DEFAUT = "claude-sonnet-5-5"
CHEMIN_JOURNAL_PAR_DEFAUT = RACINE_PROJET / "var" / "journal.sqlite3"


class TypeSource(StrEnum):
    MOCK = "mock"
    HTTP = "http"


class ModeLLM(StrEnum):
    """Qui rédige la fiche d'appel."""

    AUTO = "auto"  # Claude si une clé est configurée, sinon l'IA simulée
    ANTHROPIC = "anthropic"  # Claude via l'API Anthropic
    SIMULE = "simule"  # rejeu de rédactions enregistrées (démo sans clé)
    REPLI = "repli"  # gabarits, sans aucune IA


@dataclass(frozen=True, slots=True)
class ConfigDatahub:
    url: str | None = None
    token: str | None = None
    timeout_secondes: float = 10.0


@dataclass(frozen=True, slots=True)
class Config:
    source: TypeSource = TypeSource.MOCK
    mode_llm: ModeLLM = ModeLLM.AUTO
    modele_anthropic: str = MODELE_ANTHROPIC_PAR_DEFAUT
    cle_anthropic_presente: bool = False
    chemin_mock: Path | None = None
    datahub: ConfigDatahub = ConfigDatahub()
    chemin_journal: Path = CHEMIN_JOURNAL_PAR_DEFAUT
    duree_cache_secondes: int = 300
    latence_simulee_ms: int = 0

    @classmethod
    def depuis_environnement(cls, env: Mapping[str, str] | None = None) -> Config:
        """Construit la configuration à partir des variables d'environnement."""
        env = os.environ if env is None else env
        try:
            return cls(
                source=TypeSource(env.get("DATASOURCE", TypeSource.MOCK).strip().lower()),
                mode_llm=ModeLLM(env.get("LLM_MODE", ModeLLM.AUTO).strip().lower()),
                modele_anthropic=env.get("ANTHROPIC_MODEL", MODELE_ANTHROPIC_PAR_DEFAUT),
                cle_anthropic_presente=bool(env.get("ANTHROPIC_API_KEY")),
                chemin_mock=Path(env["MOCK_DATA_PATH"]) if env.get("MOCK_DATA_PATH") else None,
                datahub=ConfigDatahub(
                    url=env.get("DATAHUB_URL") or None,
                    token=env.get("DATAHUB_TOKEN") or None,
                    timeout_secondes=float(env.get("DATAHUB_TIMEOUT", "10")),
                ),
                chemin_journal=Path(env.get("JOURNAL_PATH", str(CHEMIN_JOURNAL_PAR_DEFAUT))),
                duree_cache_secondes=int(env.get("CACHE_SECONDES", "300")),
                latence_simulee_ms=int(env.get("LLM_LATENCE_SIMULEE_MS", "0")),
            )
        except ValueError as exc:
            raise ErreurConfiguration(f"Configuration invalide : {exc}") from exc

    @property
    def mode_llm_effectif(self) -> ModeLLM:
        """Résout le mode « auto » en un mode concret."""
        if self.mode_llm is not ModeLLM.AUTO:
            return self.mode_llm
        return ModeLLM.ANTHROPIC if self.cle_anthropic_presente else ModeLLM.SIMULE
