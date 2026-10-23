"""Catalogue des fournisseurs de LLM pris en charge.

Changer de fournisseur ne demande aucune modification de code : on renseigne
ses variables d'environnement (clé d'API, modèle, éventuellement adresse) et on
le choisit avec `LLM_MODE`. Plusieurs fournisseurs peuvent être configurés en
même temps : la fiche, le labo et le banc d'évaluation permettent de les comparer.

Deux protocoles couvrent tous les fournisseurs :
- l'API Anthropic (Claude), avec le SDK officiel `anthropic` ;
- l'API « Chat Completions » d'OpenAI, avec le SDK officiel `openai`. Mistral,
  Gemini et les serveurs de modèles locaux (Ollama, vLLM, LM Studio…) exposent
  aussi cette API : il suffit de changer l'adresse.

Ce module ne fait que décrire : la lecture de l'environnement est dans
`copilote.config`, la construction des clients dans `copilote.agent.llm`.
"""

from __future__ import annotations

from dataclasses import dataclass, field, replace
from enum import StrEnum


class ModeLLM(StrEnum):
    """Qui rédige la fiche d'appel."""

    AUTO = "auto"  # le premier fournisseur configuré, sinon l'IA simulée
    ANTHROPIC = "anthropic"  # Claude, API Anthropic
    OPENAI = "openai"  # API OpenAI
    MISTRAL = "mistral"  # Mistral AI (La Plateforme)
    GEMINI = "gemini"  # Gemini, point d'accès compatible OpenAI de l'API Google
    COMPATIBLE = "compatible"  # tout service compatible OpenAI : Ollama, vLLM, LM Studio, OpenRouter…
    SIMULE = "simule"  # rejeu de rédactions enregistrées (démo sans clé)
    REPLI = "repli"  # gabarits, sans aucune IA


class Protocole(StrEnum):
    ANTHROPIC = "anthropic"
    CHAT_COMPLETIONS = "chat_completions"


@dataclass(frozen=True, slots=True)
class Tarif:
    """Prix en dollars par million de jetons."""

    entree_par_million: float
    sortie_par_million: float

    def cout_usd(self, jetons_entree: int, jetons_sortie: int) -> float:
        return (jetons_entree * self.entree_par_million + jetons_sortie * self.sortie_par_million) / 1_000_000


# Tarifs publics de l'API Anthropic au 06/10/2026 (hors cache et traitement par lots).
# Pour les autres fournisseurs, les prix se renseignent dans la configuration
# ({PREFIXE}_PRIX_ENTREE et {PREFIXE}_PRIX_SORTIE) : ils changent souvent.
DATE_DES_TARIFS = "06/10/2026"
TARIFS_PUBLICS: dict[str, Tarif] = {
    "claude-opus-5-5": Tarif(4.00, 20.00),
    "claude-sonnet-5-5": Tarif(2.00, 10.00),
    "claude-haiku-5-5": Tarif(0.10, 0.50),
}


@dataclass(frozen=True, slots=True)
class ProfilFournisseur:
    """Ce qu'il faut savoir d'un fournisseur pour s'y connecter."""

    mode: ModeLLM
    libelle: str
    protocole: Protocole
    prefixe: str  # variables {prefixe}_MODEL, {prefixe}_BASE_URL, {prefixe}_PRIX_ENTREE…
    variable_cle: str
    url_par_defaut: str | None = None
    # Modèle par défaut seulement s'il est vérifié ; sinon il doit être configuré explicitement
    # (les noms de modèles changent vite et un nom périmé ferait échouer chaque fiche).
    modele_par_defaut: str | None = None
    cle_obligatoire: bool = True
    url_obligatoire: bool = False
    limite_jetons: str = "max_tokens"  # nom du paramètre qui plafonne la réponse

    @property
    def variable_modele(self) -> str:
        return f"{self.prefixe}_MODEL"

    @property
    def variable_url(self) -> str:
        return f"{self.prefixe}_BASE_URL"


PROFILS: dict[ModeLLM, ProfilFournisseur] = {
    p.mode: p
    for p in (
        ProfilFournisseur(
            ModeLLM.ANTHROPIC,
            "Claude (Anthropic)",
            Protocole.ANTHROPIC,
            "ANTHROPIC",
            "ANTHROPIC_API_KEY",
            modele_par_defaut="claude-sonnet-5-5",
        ),
        ProfilFournisseur(
            ModeLLM.MISTRAL,
            "Mistral AI",
            Protocole.CHAT_COMPLETIONS,
            "MISTRAL",
            "MISTRAL_API_KEY",
            url_par_defaut="https://api.mistral.ai/v1",
        ),
        ProfilFournisseur(
            ModeLLM.OPENAI,
            "OpenAI",
            Protocole.CHAT_COMPLETIONS,
            "OPENAI",
            "OPENAI_API_KEY",
            limite_jetons="max_completion_tokens",  # les modèles de raisonnement refusent max_tokens
        ),
        ProfilFournisseur(
            ModeLLM.GEMINI,
            "Gemini (Google)",
            Protocole.CHAT_COMPLETIONS,
            "GEMINI",
            "GEMINI_API_KEY",
            url_par_defaut="https://generativelanguage.googleapis.com/v1beta/openai/",
        ),
        ProfilFournisseur(
            ModeLLM.COMPATIBLE,
            "Service compatible OpenAI",
            Protocole.CHAT_COMPLETIONS,
            "LLM_COMPATIBLE",
            "LLM_COMPATIBLE_API_KEY",
            cle_obligatoire=False,  # un serveur local (Ollama, vLLM) n'en demande souvent pas
            url_obligatoire=True,
        ),
    )
}
ORDRE_AUTO = tuple(PROFILS)  # LLM_MODE=auto : le premier fournisseur utilisable dans cet ordre


@dataclass(frozen=True, slots=True)
class ConfigFournisseur:
    """Accès à un fournisseur, tel que configuré dans l'environnement."""

    profil: ProfilFournisseur
    modele: str | None = None
    cle_api: str | None = field(default=None, repr=False)  # secret : jamais affiché ni journalisé
    url: str | None = None
    nom: str | None = None  # nom affiché, ex. « Ollama » pour un service compatible
    outils_stricts: bool = False  # schéma d'outils « strict » (si le fournisseur le prend en charge)
    max_jetons_sortie: int | None = None
    tarif: Tarif | None = None  # prix configurés ; à défaut, tarifs publics connus

    @classmethod
    def pour(cls, mode: ModeLLM, **valeurs: object) -> ConfigFournisseur:
        """Configuration d'un fournisseur du catalogue, avec ses valeurs par défaut."""
        profil = PROFILS[mode]
        base = cls(profil=profil, modele=profil.modele_par_defaut, url=profil.url_par_defaut)
        return replace(base, **valeurs)  # type: ignore[arg-type]

    @property
    def manquants(self) -> list[str]:
        """Variables d'environnement à renseigner pour activer ce fournisseur."""
        p = self.profil
        manque = [p.variable_cle] if p.cle_obligatoire and not self.cle_api else []
        manque += [p.variable_modele] if not self.modele else []
        manque += [p.variable_url] if p.url_obligatoire and not self.url else []
        return manque

    @property
    def utilisable(self) -> bool:
        return not self.manquants

    @property
    def libelle(self) -> str:
        return self.nom or self.profil.libelle

    @property
    def tarif_effectif(self) -> Tarif | None:
        return self.tarif or (TARIFS_PUBLICS.get(self.modele) if self.modele else None)


LIBELLES_SANS_FOURNISSEUR = {
    ModeLLM.SIMULE: "IA simulée (rejeu de rédactions Claude)",
    ModeLLM.REPLI: "Sans IA (gabarits)",
    ModeLLM.AUTO: "Automatique",
}
MODELE_IMITE_PAR_LA_SIMULATION = "claude-sonnet-5-5"  # modèle dont l'IA simulée rejoue les rédactions


def libelle_redacteur(mode: ModeLLM) -> str:
    """Nom court d'un rédacteur, pour les rapports et la console."""
    if (profil := PROFILS.get(mode)) is not None:
        return profil.libelle
    return {ModeLLM.SIMULE: "IA simulée", ModeLLM.REPLI: "Repli (sans IA)"}.get(mode, "Automatique")
