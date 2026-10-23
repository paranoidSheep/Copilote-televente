"""File d'appels du jour : quels clients appeler, dans quel ordre, et pourquoi."""

from __future__ import annotations

from collections.abc import Sequence
from datetime import date, timedelta
from enum import StrEnum

from copilote.domaine import Client
from copilote.journal import CompteRendu

from .appels import resumer_appels
from .base import Resultat
from .habitudes import HabitudesClient, analyser_habitudes
from .manquants import StatutManquant, analyser_manquants
from .referentiel import Referentiel
from .statistiques import JourSemaine
from .stock import Pertinence, analyser_stock_client


class NiveauPriorite(StrEnum):
    HAUTE = "haute"
    MOYENNE = "moyenne"
    BASSE = "basse"


class RaisonPriorite(Resultat):
    code: str
    libelle: str
    points: int


class PrioriteAppel(Resultat):
    client: Client
    score: int
    niveau: NiveauPriorite
    raisons: list[RaisonPriorite]
    jours_habituels: list[JourSemaine]
    prochain_jour_habituel: date | None
    jours_depuis_derniere_commande: int | None
    panier_moyen_ht: float | None
    nb_manquants: int
    nb_decroches: int
    nb_opportunites_stock: int
    deja_appele_aujourdhui: bool
    rappel_prevu: date | None


class FileAppels(Resultat):
    date_du_jour: date
    appels: list[PrioriteAppel]

    @property
    def restants(self) -> list[PrioriteAppel]:
        return [a for a in self.appels if not a.deja_appele_aujourdhui]


def _rang_ca(ref: Referentiel) -> dict[str, float]:
    """Rang centile (0 à 1) de chaque client selon son chiffre d'affaires sur la période."""
    ca = {cid: sum(c.montant_ht for c in ref.commandes_client(cid)) for cid in ref.clients}
    ordonnes = sorted(ca, key=lambda cid: ca[cid])
    n = max(len(ordonnes) - 1, 1)
    return {cid: i / n for i, cid in enumerate(ordonnes)}


def evaluer_priorite(
    ref: Referentiel,
    client_id: str,
    comptes_rendus: Sequence[CompteRendu],
    rang_ca: float,
) -> PrioriteAppel:
    """Score de priorité d'un client, avec le détail des raisons (pour l'expliquer au télévendeur)."""
    poids = ref.regles.priorite
    aujourd_hui = ref.date_du_jour
    habitudes: HabitudesClient = analyser_habitudes(ref, client_id)
    manquants = analyser_manquants(ref, client_id).produits
    stock = analyser_stock_client(ref, client_id).produits
    historique = resumer_appels(comptes_rendus, client_id, aujourd_hui, ref.regles)
    raisons: list[RaisonPriorite] = []

    def ajouter(code: str, libelle: str, points: int) -> None:
        if points > 0:
            raisons.append(RaisonPriorite(code=code, libelle=libelle, points=points))

    if historique.rappel_prevu is not None and historique.rappel_prevu <= aujourd_hui:
        ajouter("rappel", f"Rappel demandé pour le {historique.rappel_prevu:%d/%m}", poids.rappel_du)

    jour = JourSemaine.de(aujourd_hui)
    demain = JourSemaine.de(aujourd_hui + timedelta(days=1))
    if jour in habitudes.jours_habituels:
        ajouter("jour_commande", f"Commande habituellement le {jour}", poids.jour_commande_aujourdhui)
    elif demain in habitudes.jours_habituels:
        ajouter("jour_commande_demain", f"Commande habituellement le {demain}", poids.jour_commande_demain)

    attente, intervalle = habitudes.jours_depuis_derniere_commande, habitudes.intervalle_median_jours
    if attente is not None and intervalle and attente > max(ref.regles.retard_minimum_jours, 1.5 * intervalle):
        ajouter("retard", f"Aucune commande depuis {attente} jours", poids.commande_en_retard)

    decroches = [m for m in manquants if m.statut is StatutManquant.DECROCHE]
    ajouter(
        "decrochage",
        f"{len(decroches)} produit(s) décroché(s)",
        min(len(decroches) * poids.par_decrochage, poids.max_decrochages),
    )
    en_retard = len(manquants) - len(decroches)
    ajouter(
        "manquants",
        f"{en_retard} produit(s) habituel(s) en retard",
        min(en_retard * poids.par_manquant, poids.max_manquants),
    )

    opportunites = [s for s in stock if s.urgent and s.pertinence >= Pertinence.DEJA_ACHETE]
    ajouter(
        "stock",
        f"{len(opportunites)} lot(s) à DLC courte qui l'intéressent",
        min(len(opportunites) * poids.par_opportunite_stock, poids.max_opportunites_stock),
    )

    if rang_ca >= 2 / 3:
        ajouter("valeur", "Client parmi les plus gros chiffres d'affaires", poids.gros_client)
    elif rang_ca >= 1 / 3:
        ajouter("valeur", "Client au chiffre d'affaires moyen", poids.client_moyen)

    if habitudes.tendance_ca_pct is not None and habitudes.tendance_ca_pct <= poids.seuil_baisse_activite_pct:
        ajouter("baisse", f"Activité en baisse ({habitudes.tendance_ca_pct} %)", poids.baisse_activite)

    score = min(100, sum(r.points for r in raisons))
    deja_appele = any(
        cr.client_id == client_id and cr.cree_le.date() == aujourd_hui for cr in comptes_rendus
    )
    niveau = (
        NiveauPriorite.HAUTE
        if score >= poids.seuil_haute
        else NiveauPriorite.MOYENNE
        if score >= poids.seuil_moyenne
        else NiveauPriorite.BASSE
    )
    return PrioriteAppel(
        client=habitudes.client,
        score=score,
        niveau=niveau,
        raisons=sorted(raisons, key=lambda r: -r.points),
        jours_habituels=habitudes.jours_habituels,
        prochain_jour_habituel=habitudes.prochain_jour_habituel,
        jours_depuis_derniere_commande=habitudes.jours_depuis_derniere_commande,
        panier_moyen_ht=habitudes.panier_moyen_ht,
        nb_manquants=len(manquants),
        nb_decroches=len(decroches),
        nb_opportunites_stock=len(opportunites),
        deja_appele_aujourdhui=deja_appele,
        rappel_prevu=historique.rappel_prevu,
    )


def construire_file_appels(
    ref: Referentiel, comptes_rendus: Sequence[CompteRendu], televendeur: str | None = None
) -> FileAppels:
    """Tous les clients (ou ceux d'un télévendeur), du plus au moins prioritaire.

    Les clients déjà appelés aujourd'hui passent en fin de liste.
    """
    rangs = _rang_ca(ref)
    appels = [
        evaluer_priorite(ref, client.id, comptes_rendus, rangs[client.id])
        for client in ref.clients.values()
        if televendeur is None or client.commercial == televendeur
    ]
    appels.sort(key=lambda a: (a.deja_appele_aujourdhui, -a.score, a.client.nom))
    return FileAppels(date_du_jour=ref.date_du_jour, appels=appels)
