"""Critères d'évaluation d'une fiche d'appel : fonctions pures, sans IA ni réseau.

Trois notes sur 100, combinées en un score global :
- **fidélité** : la rédaction respecte-t-elle les données et les règles ? Chaque
  correction des garde-fous coûte des points, de même qu'une remise citée dans
  le texte sans avoir été proposée (le télévendeur l'annoncerait au client) ;
- **couverture** : les signaux clés trouvés par les analyses (produits habituels
  en retard, lots urgents que le client achète, rappel promis) sont-ils repris
  par le rédacteur lui-même ?
- **format** : la fiche est-elle utilisable au téléphone (contact cité, accroches
  courtes, vouvoiement, résumé concis, chaque proposition argumentée) ?

Ces critères ne jugent pas le style : ils vérifient ce qui est vérifiable, pour
comparer objectivement deux versions du prompt ou deux rédacteurs.
"""

from __future__ import annotations

import re
from collections.abc import Iterable, Mapping

from copilote.analyses import ContexteClient, Pertinence, StatutManquant
from copilote.config import ModeLLM
from copilote.fiche import Fiche, ModeFiche, TypeCorrection
from copilote.fiche.repli import MAX_STOCK

from .modeles import ControleFormat, EvaluationFiche, SignalCle, TypeSignal
from .tarifs import cout_usd

PENALITES: Mapping[TypeCorrection, int] = {
    TypeCorrection.PRODUIT_INCONNU: 25,  # produit inventé
    TypeCorrection.REMISE_PLAFONNEE: 20,  # remise au-delà de ce qui est autorisé
    TypeCorrection.OFFRE_REFUSEE: 15,  # offre que le client vient de refuser
    TypeCorrection.ACCROCHE_RETIREE: 10,  # … et vantée dans une accroche
    TypeCorrection.RAPPEL_AJOUTE: 15,  # rappel promis oublié
    TypeCorrection.STOCK_COMPLETE: 10,
    TypeCorrection.ACCROCHES_COMPLETEES: 10,
    TypeCorrection.SELECTION_LIMITEE: 5,
    TypeCorrection.ACCROCHES_LIMITEES: 5,
}
PENALITE_REMISE_HORS_REGLE = 20
POIDS_FIDELITE, POIDS_COUVERTURE, POIDS_FORMAT = 0.40, 0.35, 0.25

MAX_MANQUANTS_CLES = 3  # les produits habituels en retard les plus importants
MAX_LOTS_CLES = 2  # les lots urgents les plus pertinents
LONGUEUR_MAX_ACCROCHE = 220  # environ 15 secondes à l'oral
LONGUEUR_MAX_ARGUMENT = 200
PHRASES_RESUME = range(2, 4)  # 2 ou 3 phrases, comme le demande le prompt

_TUTOIEMENT = re.compile(r"\b(tu|te|toi|ton|ta|tes|t')\b", re.IGNORECASE)
_ABREVIATIONS = re.compile(r"\b(M|Mme|Mlle|MM|Dr|St|Ste|env|etc|réf)\.", re.IGNORECASE)
_FIN_DE_PHRASE = re.compile(r"[.!?…]+(?:\s+|$)")
_REMISES_CITEES = (
    re.compile(r"[-−–]\s?(\d{1,2})\s?%"),  # « -15 % »
    re.compile(r"(\d{1,2})\s?%\s+de\s+(?:remise|réduction|rabais)", re.IGNORECASE),  # « 15 % de remise »
)


def evaluer_fiche(fiche: Fiche, contexte: ContexteClient, redacteur: ModeLLM, duree_ms: int) -> EvaluationFiche:
    remises = remises_hors_regle(fiche)
    penalites = sum(PENALITES[c.type] for c in fiche.garde_fous) + PENALITE_REMISE_HORS_REGLE * len(remises)
    fidelite = max(0, 100 - penalites)
    signaux = signaux_cles(fiche, contexte)
    couverture = round(100 * sum(s.couvert for s in signaux) / len(signaux)) if signaux else 100
    controles = controles_format(fiche)
    forme = round(100 * sum(c.reussi for c in controles) / len(controles))
    jetons_entree = fiche.trace.jetons_entree if fiche.trace else 0
    jetons_sortie = fiche.trace.jetons_sortie if fiche.trace else 0
    return EvaluationFiche(
        client_id=fiche.client.id,
        client_nom=fiche.client.nom,
        redacteur=redacteur,
        modele=fiche.modele,
        mode_obtenu=fiche.mode,
        repli_force=redacteur is not ModeLLM.REPLI and fiche.mode is ModeFiche.REPLI,
        score_global=round(POIDS_FIDELITE * fidelite + POIDS_COUVERTURE * couverture + POIDS_FORMAT * forme),
        score_fidelite=fidelite,
        score_couverture=couverture,
        score_format=forme,
        corrections=tuple(fiche.garde_fous),
        remises_hors_regle=remises,
        signaux=signaux,
        controles_format=controles,
        duree_ms=duree_ms,
        jetons_entree=jetons_entree,
        jetons_sortie=jetons_sortie,
        cout_usd=cout_usd(fiche.modele, jetons_entree, jetons_sortie) if fiche.trace else None,
    )


# ---------------------------------------------------------------------------------
# Fidélité : remises annoncées dans le texte
# ---------------------------------------------------------------------------------


def textes_au_client(fiche: Fiche) -> list[str]:
    """Ce que le télévendeur dira au client : accroches, commentaires et arguments."""
    return [
        *fiche.accroches,
        *(m.commentaire for m in fiche.produits_manquants),
        *(s.argument for s in fiche.stock_a_ecouler),
        *(s.argument for s in fiche.suggestions),
    ]


def textes_libres(fiche: Fiche) -> list[str]:
    """Tout ce que le rédacteur a écrit lui-même, résumé des habitudes compris."""
    return [fiche.resume_habitudes, *textes_au_client(fiche)]


def remises_hors_regle(fiche: Fiche) -> tuple[str, ...]:
    """Remises annoncées au client qui ne correspondent à aucune remise proposée dans la fiche.

    Le résumé des habitudes n'est pas examiné : un « -7 % » y décrit une tendance, pas une remise.
    """
    proposees = {s.remise_pct for s in fiche.stock_a_ecouler}
    constats: list[str] = []
    for texte in textes_au_client(fiche):
        for motif in _REMISES_CITEES:
            for trouve in motif.finditer(texte):
                if int(trouve.group(1)) not in proposees:
                    constats.append(f"« {trouve.group(0)} » cité, aucune remise de {trouve.group(1)} % proposée")
    return tuple(dict.fromkeys(constats))


# ---------------------------------------------------------------------------------
# Couverture des signaux clés
# ---------------------------------------------------------------------------------


def signaux_cles(fiche: Fiche, contexte: ContexteClient) -> tuple[SignalCle, ...]:
    ajoutes = {code for c in fiche.garde_fous if c.type is TypeCorrection.STOCK_COMPLETE for code in c.codes}
    manquants = {m.code for m in fiche.produits_manquants}
    stock = {s.code for s in fiche.stock_a_ecouler} - ajoutes
    refuses = set(contexte.appels.codes_refuses_recemment)

    signaux = [
        SignalCle(
            type=TypeSignal.MANQUANT_PRIORITAIRE,
            libelle=f"{m.libelle} ({'décroché' if m.statut is StatutManquant.DECROCHE else 'en retard'})",
            code=m.code,
            couvert=m.code in manquants,
        )
        for m in contexte.manquants.produits[:MAX_MANQUANTS_CLES]
    ]
    # Lots urgents d'un produit que le client achète, parmi les propositions prioritaires des analyses.
    prioritaires = [p for p in contexte.stock.produits if p.code not in refuses][:MAX_STOCK]
    lots_cles = [p for p in prioritaires if p.urgent and p.pertinence >= Pertinence.DEJA_ACHETE][:MAX_LOTS_CLES]
    signaux += [
        SignalCle(
            type=TypeSignal.LOT_URGENT_HABITUEL,
            libelle=f"{p.libelle} (DLC J+{p.jours_avant_dlc})",
            code=p.code,
            couvert=p.code in stock,
        )
        for p in lots_cles
    ]
    if contexte.appels.rappel_prevu is not None:
        oublie = any(c.type is TypeCorrection.RAPPEL_AJOUTE for c in fiche.garde_fous)
        signaux.append(
            SignalCle(
                type=TypeSignal.RAPPEL_PROMIS,
                libelle=f"Rappel promis pour le {contexte.appels.rappel_prevu:%d/%m}",
                code=None,
                couvert=not oublie,
            )
        )
    return tuple(signaux)


# ---------------------------------------------------------------------------------
# Format : utilisable au téléphone
# ---------------------------------------------------------------------------------


def nombre_de_phrases(texte: str) -> int:
    sans_abreviations = _ABREVIATIONS.sub(lambda m: m.group(1), texte.strip())
    return len([p for p in _FIN_DE_PHRASE.split(sans_abreviations) if p.strip()])


def _controle(libelle: str, defauts: Iterable[str], si_reussi: str) -> ControleFormat:
    liste = list(defauts)
    return ControleFormat(libelle=libelle, reussi=not liste, detail="; ".join(liste) if liste else si_reussi)


def controles_format(fiche: Fiche) -> tuple[ControleFormat, ...]:
    contact = fiche.client.contact.strip()
    nom_contact = contact.split()[-1] if contact else ""
    cite = not nom_contact or any(nom_contact.lower() in a.lower() for a in fiche.accroches)
    longues = [
        f"accroche {i} : {len(a)} caractères"
        for i, a in enumerate(fiche.accroches, 1)
        if len(a) > LONGUEUR_MAX_ACCROCHE
    ]
    plus_longue = max(map(len, fiche.accroches), default=0)
    phrases = nombre_de_phrases(fiche.resume_habitudes)
    arguments = [(s.code, s.argument) for s in fiche.stock_a_ecouler]
    arguments += [(s.code, s.argument) for s in fiche.suggestions]
    sans_argument = [
        *(f"{m.code} sans commentaire" for m in fiche.produits_manquants if not m.commentaire.strip()),
        *(f"{code} sans argument" for code, argument in arguments if not argument.strip()),
        *(
            f"{code} : argument de {len(argument)} caractères"
            for code, argument in arguments
            if len(argument) > LONGUEUR_MAX_ARGUMENT
        ),
    ]
    tutoiement = [m.group(0) for texte in textes_libres(fiche) for m in _TUTOIEMENT.finditer(texte)]
    return (
        ControleFormat(
            libelle="Contact cité dans une accroche",
            reussi=cite,
            detail=f"{contact or 'aucun contact renseigné'}" + ("" if cite else " : jamais nommé"),
        ),
        _controle(
            f"Accroches de {LONGUEUR_MAX_ACCROCHE} caractères au plus",
            longues,
            f"{len(fiche.accroches)} accroches, la plus longue fait {plus_longue} caractères",
        ),
        _controle("Vouvoiement", (f"« {mot} »" for mot in dict.fromkeys(tutoiement)), "aucun tutoiement"),
        ControleFormat(
            libelle="Résumé des habitudes en 2 ou 3 phrases",
            reussi=phrases in PHRASES_RESUME,
            detail=f"{phrases} phrase{'s' if phrases > 1 else ''}",
        ),
        _controle("Chaque proposition est argumentée", sans_argument, "commentaires et arguments présents et courts"),
    )
