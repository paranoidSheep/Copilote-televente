"""Agent IA : génère la fiche d'appel avec Claude (tool use), ou en mode repli.

Déroulé avec IA :
1. Claude reçoit la demande (« prépare la fiche du client X ») et quatre outils
   métier : il les appelle pour récupérer les données (en parallèle si possible).
2. Une fois les données en main, il appelle l'outil `soumettre_fiche` avec sa
   rédaction structurée (résumé, sélection de produits, arguments, accroches).
3. La fiche finale est assemblée par `agent.fiche.assembler_fiche`, qui écarte
   tout produit inventé et plafonne les remises : l'IA rédige, les outils font foi.

Mode repli : si ANTHROPIC_API_KEY est absente, ou si l'appel à l'IA échoue, la
fiche est rédigée par gabarits à partir des mêmes outils. La démo marche toujours.
"""

from __future__ import annotations

import json
import logging
import os
from typing import Any

import anthropic
from pydantic import ValidationError

from datahub.base import DataSource

from .fiche import Fiche, Redaction, assembler_fiche, redaction_repli
from .tools import DEFINITIONS_OUTILS, contexte_complet, executer_outil

logger = logging.getLogger(__name__)

MODELE_PAR_DEFAUT = "claude-sonnet-5-5"
MAX_TOURS = 6  # garde-fou : nombre maximum d'allers-retours avec Claude

PROMPT_SYSTEME = """\
Tu es le copilote d'un télévendeur chez un distributeur alimentaire (produits frais et surgelés) \
qui livre des professionnels : restaurants, cantines, EHPAD, boulangeries, traiteurs, hôtels, snacks.

Ta mission : préparer en quelques secondes une fiche d'appel claire, que le télévendeur lira juste \
avant de décrocher son téléphone.

Méthode :
1. Appelle les quatre outils de données pour le client demandé (tu peux les appeler en parallèle) : \
historique_client, produits_habituels_manquants, stock_a_ecouler, suggestions_croisees.
2. Termine en appelant l'outil soumettre_fiche, une seule fois, avec ta rédaction.

Règles impératives :
- N'utilise QUE les données renvoyées par les outils. N'invente aucun produit, prix, chiffre ou date. \
Les codes produits que tu cites doivent figurer dans les résultats des outils.
- La remise proposée pour un produit à écouler ne dépasse jamais sa remise_suggeree_pct. \
Tu peux la baisser si le produit est déjà un achat régulier du client.
- Sélectionne l'essentiel : au plus 5 produits manquants (les plus importants), 2 à 4 produits à \
écouler (les plus pertinents pour CE client et son activité), 0 à 3 suggestions.
- resume_habitudes : 2 ou 3 phrases factuelles (fréquence, jours de commande, panier moyen, produits \
phares, tendance). Montants en euros HT, au format français.
- Commentaires et arguments : une phrase courte et concrète chacun, utile au téléphone \
(ex. « idéal pour votre plat du jour », « DLC samedi, parfait pour le service du week-end »).
- accroches : 2 ou 3 phrases prêtes à dire au téléphone, naturelles, en vouvoiement, qui s'adressent \
au contact du client par son nom. Chacune s'appuie sur un élément concret de la fiche (un produit \
habituel oublié, une opportunité de stock, une nouveauté adoptée par des clients similaires).
- points_attention : 0 à 3 alertes utiles (produit « décroché » = probable achat chez un concurrent, \
baisse d'activité, longue absence de commande). Liste vide s'il n'y a rien à signaler.
- Ton professionnel, chaleureux et direct. Pas de jargon technique, pas de mention des outils.
"""

OUTIL_SOUMETTRE_FICHE = {
    "name": "soumettre_fiche",
    "description": "Soumet la rédaction finale de la fiche d'appel. À appeler une seule fois, en dernier.",
    "strict": True,
    "input_schema": {
        "type": "object",
        "additionalProperties": False,
        "required": [
            "resume_habitudes",
            "produits_manquants",
            "stock_a_ecouler",
            "suggestions",
            "accroches",
            "points_attention",
        ],
        "properties": {
            "resume_habitudes": {"type": "string", "description": "2-3 phrases sur les habitudes du client"},
            "produits_manquants": {
                "type": "array",
                "description": "Produits habituels non commandés, par ordre d'importance",
                "items": {
                    "type": "object",
                    "additionalProperties": False,
                    "required": ["code", "commentaire"],
                    "properties": {
                        "code": {"type": "string"},
                        "commentaire": {"type": "string"},
                    },
                },
            },
            "stock_a_ecouler": {
                "type": "array",
                "description": "Produits à écouler à proposer, par ordre de priorité",
                "items": {
                    "type": "object",
                    "additionalProperties": False,
                    "required": ["code", "remise_pct", "argument"],
                    "properties": {
                        "code": {"type": "string"},
                        "remise_pct": {"type": "integer", "description": "≤ remise_suggeree_pct"},
                        "argument": {"type": "string"},
                    },
                },
            },
            "suggestions": {
                "type": "array",
                "description": "Produits adoptés par des clients similaires à proposer",
                "items": {
                    "type": "object",
                    "additionalProperties": False,
                    "required": ["code", "argument"],
                    "properties": {
                        "code": {"type": "string"},
                        "argument": {"type": "string"},
                    },
                },
            },
            "accroches": {"type": "array", "items": {"type": "string"}, "description": "2 ou 3 phrases"},
            "points_attention": {"type": "array", "items": {"type": "string"}},
        },
    },
}


class ErreurAgent(RuntimeError):
    """L'agent n'a pas pu produire de rédaction exploitable."""


def modele_configure() -> str:
    """Modèle Claude utilisé (surchargeable par ANTHROPIC_MODEL)."""
    return os.environ.get("ANTHROPIC_MODEL", MODELE_PAR_DEFAUT)


def ia_disponible() -> bool:
    """Vrai si une clé d'API Anthropic est configurée."""
    return bool(os.environ.get("ANTHROPIC_API_KEY"))


def generer_fiche(
    source: DataSource,
    client_id: str,
    client_anthropic: anthropic.Anthropic | None = None,
) -> Fiche:
    """Point d'entrée : génère la fiche d'appel d'un client.

    Lève `datahub.ClientIntrouvable` si le client n'existe pas. Toute autre
    difficulté côté IA bascule en mode repli, avec un avertissement dans la fiche.
    """
    source.get_client(client_id)  # vérifie l'existence avant tout calcul
    # Calcul déterministe des données de référence (sert à l'assemblage et au repli)
    contexte = contexte_complet(source, client_id)

    if client_anthropic is None and not ia_disponible():
        return assembler_fiche(
            contexte, redaction_repli(contexte), mode="repli",
            avertissement="ANTHROPIC_API_KEY absente : fiche rédigée sans IA.",
        )

    modele = modele_configure()
    try:
        client_anthropic = client_anthropic or anthropic.Anthropic()
        redaction = rediger_avec_claude(client_anthropic, modele, source, client_id)
        return assembler_fiche(contexte, redaction, mode="ia", modele=modele)
    except anthropic.APIConnectionError as exc:
        raison = "service IA injoignable"
        logger.warning("Claude injoignable : %s", exc)
    except anthropic.RateLimitError as exc:
        raison = "limite d'utilisation de l'IA atteinte"
        logger.warning("Limite de débit Anthropic : %s", exc)
    except anthropic.APIStatusError as exc:
        raison = f"erreur du service IA ({exc.status_code})"
        logger.warning("Erreur API Anthropic : %s", exc)
    except ErreurAgent as exc:
        raison = str(exc)
        logger.warning("Rédaction IA inexploitable : %s", exc)

    return assembler_fiche(
        contexte, redaction_repli(contexte), mode="repli",
        avertissement=f"IA indisponible ({raison}) : fiche rédigée sans IA.",
    )


def rediger_avec_claude(
    client_anthropic: anthropic.Anthropic, modele: str, source: DataSource, client_id: str
) -> Redaction:
    """Boucle de tool use : Claude appelle les outils métier puis soumet sa rédaction."""
    client = source.get_client(client_id)
    messages: list[dict[str, Any]] = [
        {
            "role": "user",
            "content": (
                f"Prépare la fiche d'appel du client {client.id} : {client.nom} "
                f"({client.type}, {client.ville}), contact : {client.contact}. "
                f"Nous sommes le {source.date_du_jour():%d/%m/%Y}."
            ),
        }
    ]
    outils = [*DEFINITIONS_OUTILS, OUTIL_SOUMETTRE_FICHE]
    relance_faite = False

    for _ in range(MAX_TOURS):
        reponse = client_anthropic.beta.messages.create(
            model=modele,
            max_tokens=16000,
            system=PROMPT_SYSTEME,
            tools=outils,
            messages=messages,
            # Effort « medium » : bon compromis qualité / latence pour un enchaînement d'outils
            output_config={"effort": "medium"},
            # Si le modèle décline la requête, l'API bascule automatiquement sur un autre modèle
            betas=["server-side-fallback-2026-07-01"],
            fallbacks="default",
        )

        if reponse.stop_reason == "refusal":
            raise ErreurAgent("le modèle a refusé la requête")
        if reponse.stop_reason == "max_tokens":
            raise ErreurAgent("réponse tronquée (max_tokens)")

        # On renvoie toujours le contenu complet (blocs de réflexion inclus) à l'API
        messages.append({"role": "assistant", "content": reponse.content})
        appels = [b for b in reponse.content if b.type == "tool_use"]

        # La rédaction finale est arrivée : on s'arrête là
        for appel in appels:
            if appel.name == "soumettre_fiche":
                try:
                    return Redaction.model_validate(appel.input)
                except ValidationError as exc:
                    raise ErreurAgent(f"rédaction mal formée : {exc.error_count()} erreur(s)") from exc

        if not appels:
            # Claude a répondu en texte sans soumettre la fiche : une seule relance
            if relance_faite:
                raise ErreurAgent("le modèle n'a pas soumis de fiche")
            relance_faite = True
            messages.append({"role": "user", "content": "Appelle maintenant l'outil soumettre_fiche avec ta rédaction."})
            continue

        # Exécution des outils métier ; tous les résultats repartent dans un seul message
        resultats = []
        for appel in appels:
            try:
                contenu = executer_outil(source, appel.name, appel.input)
                resultats.append(
                    {
                        "type": "tool_result",
                        "tool_use_id": appel.id,
                        "content": json.dumps(contenu, ensure_ascii=False, default=str),
                    }
                )
            except Exception as exc:  # une erreur d'outil est renvoyée à Claude, pas propagée
                logger.warning("Échec de l'outil %s : %s", appel.name, exc)
                resultats.append(
                    {"type": "tool_result", "tool_use_id": appel.id, "content": f"Erreur : {exc}", "is_error": True}
                )
        messages.append({"role": "user", "content": resultats})

    raise ErreurAgent(f"pas de fiche après {MAX_TOURS} échanges")
