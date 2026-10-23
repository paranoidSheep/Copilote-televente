"""Configuration de l'application, lue une seule fois depuis l'environnement.

Toute la configuration passe par l'objet `Config` (immuable et typé) : aucun
autre module ne lit `os.environ` directement. Les tests construisent leur
propre `Config` sans toucher à l'environnement.
"""

from __future__ import annotations

import os
from collections.abc import Mapping
from dataclasses import dataclass, field
from datetime import date
from enum import StrEnum
from pathlib import Path

from copilote.domaine import ErreurConfiguration
from copilote.fournisseurs import ORDRE_AUTO, PROFILS, ConfigFournisseur, ModeLLM, ProfilFournisseur, Tarif

# ModeLLM est défini dans le catalogue des fournisseurs et réexporté ici, où il a toujours été importé.
__all__ = ["DOSSIER_DONNEES_PAR_DEFAUT", "Config", "ConfigDatahub", "ConfigSecurite", "ModeLLM", "TypeSource"]

RACINE_PROJET = Path(__file__).resolve().parent.parent
DOSSIER_DONNEES_PAR_DEFAUT = RACINE_PROJET / "var"


class TypeSource(StrEnum):
    MOCK = "mock"
    HTTP = "http"


@dataclass(frozen=True, slots=True)
class ConfigDatahub:
    url: str | None = None
    token: str | None = None
    timeout_secondes: float = 10.0
    date_reference: date | None = None  # date du jour figée (recette sur extraction ou simulateur)


@dataclass(frozen=True, slots=True)
class ConfigSecurite:
    authentification: bool = True  # désactivable uniquement pour un poste de développement
    secret_session: str | None = None  # obligatoire en production (sinon : secret éphémère)
    cookie_securise: bool = False  # cookie « Secure » : à activer derrière HTTPS
    duree_session_heures: int = 12
    documentation_api: bool = True  # /docs et /openapi.json


def _booleen(valeur: str) -> bool:
    if valeur.strip().lower() in {"1", "true", "oui", "on", "yes"}:
        return True
    if valeur.strip().lower() in {"0", "false", "non", "off", "no"}:
        return False
    raise ValueError(f"valeur booléenne invalide : {valeur!r}")


def _fournisseur(profil: ProfilFournisseur, env: Mapping[str, str]) -> ConfigFournisseur:
    """Lit {PREFIXE}_MODEL, {PREFIXE}_BASE_URL, la clé, les prix et options d'un fournisseur."""
    p = profil.prefixe

    def lire(suffixe: str) -> str | None:
        return env.get(f"{p}_{suffixe}", "").strip() or None

    prix_entree, prix_sortie = lire("PRIX_ENTREE"), lire("PRIX_SORTIE")
    tarif = None
    if prix_entree is not None or prix_sortie is not None:
        tarif = Tarif(float((prix_entree or "0").replace(",", ".")), float((prix_sortie or "0").replace(",", ".")))
    max_jetons = lire("MAX_TOKENS")
    return ConfigFournisseur.pour(
        profil.mode,
        modele=lire("MODEL") or profil.modele_par_defaut,
        cle_api=env.get(profil.variable_cle, "").strip() or None,
        url=lire("BASE_URL") or profil.url_par_defaut,
        nom=lire("NOM"),
        outils_stricts=_booleen(lire("OUTILS_STRICTS") or "non"),
        max_jetons_sortie=int(max_jetons) if max_jetons else None,
        tarif=tarif,
    )


@dataclass(frozen=True, slots=True)
class Config:
    source: TypeSource = TypeSource.MOCK
    mode_llm: ModeLLM = ModeLLM.AUTO
    fournisseurs: Mapping[ModeLLM, ConfigFournisseur] = field(default_factory=dict)
    chemin_mock: Path | None = None
    datahub: ConfigDatahub = ConfigDatahub()
    dossier_donnees: Path = DOSSIER_DONNEES_PAR_DEFAUT
    chemin_journal_force: Path | None = None
    duree_cache_secondes: int = 300
    latence_simulee_ms: int = 0
    securite: ConfigSecurite = ConfigSecurite()
    format_journaux: str = "texte"  # « texte » ou « json » (journaux structurés)

    @classmethod
    def depuis_environnement(cls, env: Mapping[str, str] | None = None) -> Config:
        """Construit la configuration à partir des variables d'environnement."""
        env = os.environ if env is None else env
        try:
            return cls(
                source=TypeSource(env.get("DATASOURCE", TypeSource.MOCK).strip().lower()),
                mode_llm=ModeLLM(env.get("LLM_MODE", ModeLLM.AUTO).strip().lower()),
                fournisseurs={mode: _fournisseur(profil, env) for mode, profil in PROFILS.items()},
                chemin_mock=Path(env["MOCK_DATA_PATH"]) if env.get("MOCK_DATA_PATH") else None,
                datahub=ConfigDatahub(
                    url=env.get("DATAHUB_URL") or None,
                    token=env.get("DATAHUB_TOKEN") or None,
                    timeout_secondes=float(env.get("DATAHUB_TIMEOUT", "10")),
                    date_reference=(
                        date.fromisoformat(env["DATAHUB_DATE_REFERENCE"]) if env.get("DATAHUB_DATE_REFERENCE") else None
                    ),
                ),
                dossier_donnees=Path(env.get("DOSSIER_DONNEES", str(DOSSIER_DONNEES_PAR_DEFAUT))),
                chemin_journal_force=Path(env["JOURNAL_PATH"]) if env.get("JOURNAL_PATH") else None,
                duree_cache_secondes=int(env.get("CACHE_SECONDES", "300")),
                latence_simulee_ms=int(env.get("LLM_LATENCE_SIMULEE_MS", "0")),
                securite=ConfigSecurite(
                    authentification=_booleen(env.get("AUTHENTIFICATION", "oui")),
                    secret_session=env.get("SESSION_SECRET") or None,
                    cookie_securise=_booleen(env.get("COOKIE_SECURISE", "non")),
                    duree_session_heures=int(env.get("DUREE_SESSION_HEURES", "12")),
                    documentation_api=_booleen(env.get("DOCUMENTATION_API", "oui")),
                ),
                format_journaux=env.get("FORMAT_JOURNAUX", "texte").strip().lower(),
            )
        except ValueError as exc:
            raise ErreurConfiguration(f"Configuration invalide : {exc}") from exc

    @property
    def chemin_journal(self) -> Path:
        """Journal local des comptes-rendus d'appels."""
        return self.chemin_journal_force or self.dossier_donnees / "journal.sqlite3"

    @property
    def chemin_evaluations(self) -> Path:
        """Historique du banc d'évaluation de l'IA."""
        return self.dossier_donnees / "evaluations.sqlite3"

    @property
    def chemin_utilisateurs(self) -> Path:
        """Comptes utilisateurs du copilote."""
        return self.dossier_donnees / "utilisateurs.sqlite3"

    @property
    def mode_llm_effectif(self) -> ModeLLM:
        """Résout le mode « auto » en un mode concret."""
        if self.mode_llm is not ModeLLM.AUTO:
            return self.mode_llm
        return next(iter(self.fournisseurs_utilisables), ModeLLM.SIMULE)

    @property
    def fournisseurs_utilisables(self) -> list[ModeLLM]:
        """Fournisseurs entièrement configurés, dans l'ordre de préférence de LLM_MODE=auto."""
        return [m for m in ORDRE_AUTO if (c := self.fournisseurs.get(m)) is not None and c.utilisable]

    @property
    def avertissements(self) -> list[str]:
        """Fournisseurs à moitié configurés (ex. clé sans modèle) : signalés au démarrage."""
        messages = []
        for mode, c in self.fournisseurs.items():
            renseigne = c.cle_api or (c.modele and c.modele != c.profil.modele_par_defaut)
            if renseigne and not c.utilisable:
                manque = ", ".join(c.manquants)
                messages.append(f"{c.libelle} n'est pas activé : {manque} à renseigner.")
            if mode is self.mode_llm and not c.utilisable:
                messages.append(f"LLM_MODE={mode} mais {c.libelle} n'est pas configuré : fiches rédigées sans IA.")
        return messages
