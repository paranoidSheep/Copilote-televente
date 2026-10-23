"""Mode repli : rédaction de la fiche par gabarits, sans aucune IA.

Utilisé quand l'IA est désactivée ou indisponible, et pour compléter une
rédaction IA incomplète (accroches manquantes). Même données, même garde-fous.
"""

from __future__ import annotations

from collections.abc import Sequence

from copilote.analyses import (
    ContexteClient,
    HabitudesClient,
    HistoriqueAppels,
    MotifEcoulement,
    ProduitManquant,
    PropositionStock,
    StatutManquant,
    SuggestionCroisee,
)

from . import formatage as fmt
from .modeles import Redaction, RedactionManquant, RedactionStock, RedactionSuggestion

MAX_MANQUANTS = 5
MAX_STOCK = 4
MAX_SUGGESTIONS = 3
MAX_ACCROCHES = 3


def rediger_sans_ia(contexte: ContexteClient) -> Redaction:
    """Rédige la fiche à partir des seuls résultats des analyses."""
    refuses = set(contexte.appels.codes_refuses_recemment)
    manquants = contexte.manquants.produits[:MAX_MANQUANTS]
    stock = [s for s in contexte.stock.produits if s.code not in refuses][:MAX_STOCK]
    suggestions = [s for s in contexte.suggestions.produits if s.code not in refuses][:MAX_SUGGESTIONS]
    type_client = contexte.habitudes.client.type

    return Redaction(
        resume_habitudes=resume_habitudes(contexte.habitudes),
        produits_manquants=[RedactionManquant(code=m.code, commentaire=_commentaire_manquant(m)) for m in manquants],
        stock_a_ecouler=[
            RedactionStock(code=s.code, remise_pct=s.remise_suggeree_pct, argument=argument_stock(s)) for s in stock
        ],
        suggestions=[
            RedactionSuggestion(
                code=s.code,
                argument=(
                    f"Acheté régulièrement par {fmt.pluriel(s.nb_clients_similaires_acheteurs, 'autre client')} "
                    f"de type « {type_client} » ({s.taux_adoption_pct} % d'entre eux), jamais commandé ici."
                ),
            )
            for s in suggestions
        ],
        accroches=accroches_gabarits(
            contexte.habitudes, manquants, [(s, s.remise_suggeree_pct) for s in stock], suggestions
        ),
        points_attention=points_attention(contexte.habitudes, manquants, contexte.appels),
    )


def resume_habitudes(h: HabitudesClient) -> str:
    if not h.nb_commandes:
        return "Aucune commande sur les 6 derniers mois : client à réactiver."
    jours = fmt.liste([str(j) for j in h.jours_habituels]) or "sans jour fixe"
    phrases = [
        f"{h.client.type} qui commande en moyenne {fmt.nombre(h.commandes_par_semaine)} fois par semaine "
        f"({jours}), pour un panier moyen de {fmt.euros(h.panier_moyen_ht or 0)} HT."
    ]
    phares = [p.libelle for p in h.produits_recurrents[:3]]
    if phares:
        phrases.append(f"Produits phares : {fmt.liste(phares)}.")
    if h.tendance_ca_pct is not None:
        if h.tendance_ca_pct >= 5:
            phrases.append(f"Activité en hausse ({h.tendance_ca_pct:+d} % sur 3 mois).")
        elif h.tendance_ca_pct <= -5:
            phrases.append(f"Activité en baisse ({h.tendance_ca_pct:+d} % sur 3 mois).")
        else:
            phrases.append("Activité stable sur 3 mois.")
    return " ".join(phrases)


def _commentaire_manquant(m: ProduitManquant) -> str:
    texte = (
        f"Commandé d'habitude tous les {fmt.jours(m.rythme_habituel_jours)}, "
        f"plus rien depuis {m.jours_depuis_derniere_commande} jours."
    )
    if m.statut is StatutManquant.DECROCHE:
        texte += " Possible achat chez un concurrent : à questionner."
    return texte


def argument_stock(s: PropositionStock) -> str:
    if MotifEcoulement.DLC_COURTE in s.motifs:
        return (
            f"Lot à DLC du {fmt.date_longue(s.dlc)} (J+{s.jours_avant_dlc}) : à proposer pour une utilisation rapide."
        )
    return "Stock important sur ce produit : remise pour accélérer l'écoulement."


def accroches_gabarits(
    habitudes: HabitudesClient,
    manquants: Sequence[ProduitManquant],
    stock: Sequence[tuple[PropositionStock, int]],
    suggestions: Sequence[SuggestionCroisee],
) -> list[str]:
    """2 ou 3 phrases d'accroche construites sur les éléments les plus forts de la fiche.

    La première salue toujours l'interlocuteur par son nom.
    """
    contact = habitudes.client.contact or "Madame, Monsieur"
    pour = f" pour {fmt.jour_et_date(habitudes.prochain_jour_habituel)}" if habitudes.prochain_jour_habituel else ""
    accroches: list[str] = []
    if manquants:
        m = manquants[0]
        accroches.append(
            f"Je prépare votre commande{pour} : je ne vois pas de "
            f"{fmt.minuscule_initiale(m.libelle)} depuis quelque temps, je vous en remets "
            f"{fmt.quantite(m.quantite_habituelle, m.unite)} comme d'habitude ?"
        )
    if stock:
        s, remise = stock[0]
        prix = s.prix_unitaire_ht * (1 - remise / 100)
        accroches.append(
            f"J'ai une belle opportunité cette semaine sur {fmt.minuscule_initiale(s.libelle)} : "
            f"{remise} % de remise, soit {fmt.euros(prix)} HT le {s.unite}. Je vous en réserve ?"
        )
    if suggestions:
        g = suggestions[0]
        accroches.append(
            f"D'autres établissements comme le vôtre ont adopté {fmt.minuscule_initiale(g.libelle)} ; "
            "voulez-vous que je vous en glisse un pour essayer ?"
        )
    if len(accroches) < 2:
        accroches.append(f"Avez-vous besoin de compléter votre commande{pour} ?")
    if len(accroches) < 2:
        accroches.append("Avez-vous des besoins particuliers cette semaine : événement, nouveau plat à la carte ?")
    accroches[0] = f"Bonjour {contact}, {fmt.minuscule_initiale(accroches[0])}"
    return accroches[:MAX_ACCROCHES]


def points_attention(
    habitudes: HabitudesClient, manquants: Sequence[ProduitManquant], appels: HistoriqueAppels
) -> list[str]:
    points: list[str] = []
    if appels.rappel_prevu is not None:
        points.append(f"Le client a demandé à être rappelé le {fmt.date_longue(appels.rappel_prevu)}.")
    decroches = [m.libelle for m in manquants if m.statut is StatutManquant.DECROCHE]
    if decroches:
        points.append(f"Produits décrochés (probable concurrent) : {fmt.liste(decroches)}.")
    if habitudes.tendance_ca_pct is not None and habitudes.tendance_ca_pct <= -10:
        points.append(f"Chiffre d'affaires en baisse de {abs(habitudes.tendance_ca_pct)} % sur 3 mois.")
    attente, intervalle = habitudes.jours_depuis_derniere_commande, habitudes.intervalle_median_jours
    if attente is not None and intervalle and attente > max(7, 2 * intervalle):
        points.append(
            f"Aucune commande depuis {attente} jours, contre une tous les {fmt.jours(intervalle)} d'habitude."
        )
    return points
