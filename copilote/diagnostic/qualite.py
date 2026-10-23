"""Contrôle qualité des données ERP : règles pures, sans accès réseau.

Deux familles de règles :
- les règles « écartées » reprennent les écarts produits par
  `analyses.exploitabilite` (même code, donc même vérité que les analyses) ;
- les règles « signalées » détectent des données exploitables mais douteuses,
  qui dégradent les fiches sans les fausser complètement.

Chaque règle explique son impact en clair : le rapport s'adresse aux
responsables commerciaux et à l'équipe ERP, pas seulement aux développeurs.
"""

from __future__ import annotations

from collections import defaultdict
from collections.abc import Callable, Iterator
from dataclasses import dataclass
from datetime import date
from statistics import median

from copilote.analyses import DonneesExploitables, MotifEcart, filtrer_exploitables
from copilote.domaine import Client, Commande, Famille, Lot, Produit

from .modeles import Exemple, Gravite, ResultatRegle, Traitement, Volumes

MAX_EXEMPLES = 8
FACTEUR_QUANTITE_ABERRANTE = 10  # au-delà de 10 fois la quantité médiane du produit
MIN_LIGNES_POUR_MEDIANE = 5  # en dessous, la médiane n'est pas représentative


@dataclass(frozen=True, slots=True)
class DonneesBrutes:
    """Données telles que reçues du datahub, avant toute mise à l'écart."""

    date_du_jour: date
    clients: tuple[Client, ...]
    produits: tuple[Produit, ...]
    commandes: tuple[Commande, ...]
    lots: tuple[Lot, ...]


type Detecteur = Callable[[DonneesExploitables], Iterator[Exemple]]


@dataclass(frozen=True, slots=True)
class Regle:
    code: str
    libelle: str
    gravite: Gravite
    traitement: Traitement
    impact: str
    detecter: Detecteur


# ---------------------------------------------------------------------------------
# Détecteurs
# ---------------------------------------------------------------------------------


def _ecarts(motif: MotifEcart) -> Detecteur:
    """Détecteur qui relit les écarts décidés par les analyses."""

    def detecter(donnees: DonneesExploitables) -> Iterator[Exemple]:
        for ecart in donnees.ecarts:
            if ecart.motif is motif:
                yield Exemple(identifiant=ecart.identifiant, detail=ecart.detail)

    return detecter


def _prix_nuls(donnees: DonneesExploitables) -> Iterator[Exemple]:
    for produit in donnees.produits.values():
        if produit.prix_unitaire_ht <= 0:
            yield Exemple(identifiant=produit.code, detail=f"{produit.libelle} : prix tarif à 0 €")


def _durees_de_vie_nulles(donnees: DonneesExploitables) -> Iterator[Exemple]:
    # Seul le frais en dépend : le seuil de DLC courte du surgelé est un nombre de jours fixe.
    for produit in donnees.produits.values():
        if produit.famille is Famille.FRAIS and produit.duree_vie_jours <= 0:
            yield Exemple(identifiant=produit.code, detail=f"{produit.libelle} : durée de vie à 0 jour")


def _lots_recus_apres_dlc(donnees: DonneesExploitables) -> Iterator[Exemple]:
    for lot in donnees.lots:
        if lot.date_reception > lot.dlc:
            detail = f"{lot.produit_code} reçu le {lot.date_reception:%d/%m/%Y}, DLC au {lot.dlc:%d/%m/%Y}"
            yield Exemple(identifiant=lot.id, detail=detail)


def _quantites_aberrantes(donnees: DonneesExploitables) -> Iterator[Exemple]:
    quantites: dict[str, list[float]] = defaultdict(list)
    for commande in donnees.commandes:
        for ligne in commande.lignes:
            quantites[ligne.produit_code].append(ligne.quantite)
    medianes = {code: median(q) for code, q in quantites.items() if len(q) >= MIN_LIGNES_POUR_MEDIANE}
    for commande in donnees.commandes:
        for ligne in commande.lignes:
            habituelle = medianes.get(ligne.produit_code)
            if habituelle is not None and ligne.quantite > FACTEUR_QUANTITE_ABERRANTE * habituelle:
                detail = f"{ligne.produit_code} : {ligne.quantite:g} commandés, {habituelle:g} habituellement"
                yield Exemple(identifiant=commande.id, detail=detail)


def _clients_sans_televendeur(donnees: DonneesExploitables) -> Iterator[Exemple]:
    for client in donnees.clients.values():
        if not client.commercial.strip():
            yield Exemple(identifiant=client.id, detail=f"{client.nom} : champ « commercial » vide")


def _clients_sans_commande(donnees: DonneesExploitables) -> Iterator[Exemple]:
    actifs = {c.client_id for c in donnees.commandes}
    for client in donnees.clients.values():
        if client.id not in actifs:
            yield Exemple(identifiant=client.id, detail=f"{client.nom} ({client.type}, {client.ville})")


def _clients_sans_telephone(donnees: DonneesExploitables) -> Iterator[Exemple]:
    for client in donnees.clients.values():
        if not client.telephone.strip():
            yield Exemple(identifiant=client.id, detail=f"{client.nom} : aucun numéro de téléphone")


# ---------------------------------------------------------------------------------
# Catalogue des règles, de la plus grave à la moins grave
# ---------------------------------------------------------------------------------

CRITIQUE, ALERTE, INFO = Gravite.CRITIQUE, Gravite.ALERTE, Gravite.INFO
ECARTE, SIGNALE = Traitement.ECARTE, Traitement.SIGNALE

REGLES: tuple[Regle, ...] = (
    Regle(
        "client_duplique",
        "Identifiant client en double",
        CRITIQUE,
        ECARTE,
        "Deux fiches clients partagent un identifiant : seule la première est utilisée.",
        _ecarts(MotifEcart.CLIENT_DUPLIQUE),
    ),
    Regle(
        "produit_duplique",
        "Code produit en double",
        CRITIQUE,
        ECARTE,
        "Prix et libellé ambigus : seule la première fiche produit est utilisée.",
        _ecarts(MotifEcart.PRODUIT_DUPLIQUE),
    ),
    Regle(
        "commande_dupliquee",
        "Commande en double",
        CRITIQUE,
        ECARTE,
        "Compter deux fois une commande fausserait les habitudes et le panier moyen : le doublon est ignoré.",
        _ecarts(MotifEcart.COMMANDE_DUPLIQUEE),
    ),
    Regle(
        "commande_client_inconnu",
        "Commande d'un client inconnu",
        CRITIQUE,
        ECARTE,
        "La commande est rattachée à un client absent du référentiel : elle est ignorée.",
        _ecarts(MotifEcart.COMMANDE_CLIENT_INCONNU),
    ),
    Regle(
        "ligne_produit_inconnu",
        "Ligne de commande sur un produit inconnu",
        CRITIQUE,
        ECARTE,
        "Produit absent du catalogue : la ligne est ignorée, les habitudes et le CA du client sont incomplets.",
        _ecarts(MotifEcart.LIGNE_PRODUIT_INCONNU),
    ),
    Regle(
        "lot_produit_inconnu",
        "Lot de stock sur un produit inconnu",
        CRITIQUE,
        ECARTE,
        "Lot rattaché à un produit absent du catalogue : il n'est jamais proposé.",
        _ecarts(MotifEcart.LOT_PRODUIT_INCONNU),
    ),
    Regle(
        "commande_future",
        "Commande datée dans le futur",
        ALERTE,
        ECARTE,
        "Date postérieure à aujourd'hui (date de livraison ? erreur de saisie ?) : la commande est ignorée.",
        _ecarts(MotifEcart.COMMANDE_FUTURE),
    ),
    Regle(
        "lot_perime",
        "Lot périmé déclaré en stock",
        ALERTE,
        ECARTE,
        "DLC dépassée : le lot n'est jamais proposé à la vente. À sortir du stock disponible dans l'ERP.",
        _ecarts(MotifEcart.LOT_PERIME),
    ),
    Regle(
        "prix_nul",
        "Produit sans prix",
        ALERTE,
        SIGNALE,
        "Prix tarif à 0 € : CA, remises et valeur du stock sont calculés à 0 € pour ce produit.",
        _prix_nuls,
    ),
    Regle(
        "duree_vie_nulle",
        "Durée de vie non renseignée (frais)",
        ALERTE,
        SIGNALE,
        "Sans durée de vie, la DLC courte est détectée avec le seuil minimal : l'alerte peut arriver tard.",
        _durees_de_vie_nulles,
    ),
    Regle(
        "lot_recu_apres_dlc",
        "Lot reçu après sa DLC",
        ALERTE,
        SIGNALE,
        "Dates de réception et de DLC incohérentes : l'urgence calculée pour ce lot est peut-être fausse.",
        _lots_recus_apres_dlc,
    ),
    Regle(
        "quantite_aberrante",
        "Quantité anormale",
        ALERTE,
        SIGNALE,
        f"Plus de {FACTEUR_QUANTITE_ABERRANTE} fois la quantité habituelle (un zéro de trop ?) : "
        "les habitudes et la rotation du stock sont faussées.",
        _quantites_aberrantes,
    ),
    Regle(
        "client_sans_televendeur",
        "Client sans télévendeur",
        ALERTE,
        SIGNALE,
        "Absent de toutes les files d'appels individuelles : seul un responsable le voit.",
        _clients_sans_televendeur,
    ),
    Regle(
        "client_sans_commande",
        "Client sans commande sur la période",
        INFO,
        SIGNALE,
        "Aucune habitude connue : la fiche se limite aux découvertes et au stock à écouler.",
        _clients_sans_commande,
    ),
    Regle(
        "client_sans_telephone",
        "Client sans téléphone",
        INFO,
        SIGNALE,
        "Le télévendeur doit chercher le numéro ailleurs avant d'appeler.",
        _clients_sans_telephone,
    ),
)


# ---------------------------------------------------------------------------------
# Points d'entrée
# ---------------------------------------------------------------------------------


def controler_qualite(brutes: DonneesBrutes, regles: tuple[Regle, ...] = REGLES) -> tuple[ResultatRegle, ...]:
    """Applique toutes les règles ; le résultat contient aussi les règles sans anomalie."""
    exploitables = filtrer_exploitables(
        brutes.date_du_jour, brutes.clients, brutes.produits, brutes.commandes, brutes.lots
    )
    resultats = []
    for regle in regles:
        exemples = list(regle.detecter(exploitables))
        resultats.append(
            ResultatRegle(
                code=regle.code,
                libelle=regle.libelle,
                gravite=regle.gravite,
                traitement=regle.traitement,
                impact=regle.impact,
                nombre=len(exemples),
                exemples=tuple(exemples[:MAX_EXEMPLES]),
            )
        )
    return tuple(resultats)


def mesurer_volumes(brutes: DonneesBrutes) -> Volumes:
    dates = [c.date for c in brutes.commandes]
    return Volumes(
        clients=len(brutes.clients),
        produits=len(brutes.produits),
        commandes=len(brutes.commandes),
        lignes=sum(len(c.lignes) for c in brutes.commandes),
        lots=len(brutes.lots),
        premiere_commande=min(dates, default=None),
        derniere_commande=max(dates, default=None),
    )
