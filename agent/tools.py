"""Outils métier du copilote : calculs déterministes sur les données du datahub.

Ces fonctions sont le « socle de vérité » de la fiche d'appel :
- elles font tous les calculs (fréquences, paniers, retards, remises) ;
- l'IA ne fait que sélectionner et formuler à partir de leurs résultats ;
- elles sont testées unitairement (voir `tests/test_tools.py`).

Chaque fonction renvoie un dictionnaire sérialisable en JSON, directement
transmissible à Claude comme résultat d'outil.
"""

from __future__ import annotations

from collections import Counter, defaultdict
from datetime import date, timedelta
from statistics import median
from typing import Any

from datahub.base import Commande, DataSource, Produit

# ---------------------------------------------------------------------------
# Paramètres métier (centralisés ici pour être faciles à ajuster)
# ---------------------------------------------------------------------------

PERIODE_ANALYSE_JOURS = 183  # ~6 mois d'historique analysé
SEUIL_PRODUIT_RECURRENT = 0.30  # présent dans au moins 30 % des commandes…
MIN_COMMANDES_RECURRENT = 3  # … et au moins 3 fois
FACTEUR_RETARD = 1.5  # « manquant » si non commandé depuis 1,5 × son rythme habituel
RETARD_MINIMUM_JOURS = 7  # on ne signale jamais un retard de moins d'une semaine
FACTEUR_DECROCHAGE = 3.0  # au-delà de 3 × le rythme : probable perte du produit

FENETRE_ROTATION_JOURS = 28  # rotation du stock calculée sur 4 semaines
DLC_COURTE_SURGELE_JOURS = 30
SEUIL_SURSTOCK_JOURS = {"frais": 14, "surgele": 90}  # couverture au-delà de laquelle on parle de surstock
REMISE_MAX_PCT = 30


# ---------------------------------------------------------------------------
# Petits utilitaires
# ---------------------------------------------------------------------------

JOURS_SEMAINE = ["lundi", "mardi", "mercredi", "jeudi", "vendredi", "samedi", "dimanche"]


def _catalogue(source: DataSource) -> dict[str, Produit]:
    return {p.code: p for p in source.get_products()}


def _historique(source: DataSource, client_id: str) -> list[Commande]:
    debut = source.date_du_jour() - timedelta(days=PERIODE_ANALYSE_JOURS)
    return source.get_order_history(client_id, depuis=debut)


def _dates_par_produit(commandes: list[Commande]) -> dict[str, list[date]]:
    """Pour chaque produit, les dates (triées, sans doublon) où il a été commandé."""
    dates: dict[str, set[date]] = defaultdict(set)
    for cmd in commandes:
        for ligne in cmd.lignes:
            dates[ligne.produit_code].add(cmd.date)
    return {code: sorted(d) for code, d in dates.items()}


def _intervalle_median(dates: list[date]) -> float | None:
    """Intervalle médian en jours entre deux dates successives.

    La médiane (plutôt que la moyenne) neutralise les longues interruptions
    ponctuelles : vacances scolaires, fermeture annuelle…
    """
    if len(dates) < 2:
        return None
    return float(median((b - a).days for a, b in zip(dates, dates[1:])))


def _quantites_par_produit(commandes: list[Commande]) -> dict[str, list[float]]:
    quantites: dict[str, list[float]] = defaultdict(list)
    for cmd in commandes:
        for ligne in cmd.lignes:
            quantites[ligne.produit_code].append(ligne.quantite)
    return quantites


def _produits_recurrents(commandes: list[Commande]) -> dict[str, dict[str, Any]]:
    """Produits présents dans une part significative des commandes du client."""
    if not commandes:
        return {}
    nb = len(commandes)
    dates = _dates_par_produit(commandes)
    quantites = _quantites_par_produit(commandes)
    recurrents = {}
    for code, d in dates.items():
        frequence = len(d) / nb
        if frequence >= SEUIL_PRODUIT_RECURRENT and len(d) >= MIN_COMMANDES_RECURRENT:
            recurrents[code] = {
                "frequence": frequence,
                "nb_commandes": len(d),
                "dates": d,
                "quantite_habituelle": round(median(quantites[code]), 1),
            }
    return recurrents


def _arrondi(x: float, n: int = 1) -> float:
    return round(x, n)


# ---------------------------------------------------------------------------
# Outil 1 : historique et habitudes du client
# ---------------------------------------------------------------------------


def historique_client(source: DataSource, client_id: str) -> dict[str, Any]:
    """Résumé chiffré des habitudes d'achat d'un client sur les 6 derniers mois."""
    client = source.get_client(client_id)
    aujourd_hui = source.date_du_jour()
    commandes = _historique(source, client_id)
    catalogue = _catalogue(source)

    resultat: dict[str, Any] = {
        "client": client.model_dump(),
        "date_du_jour": aujourd_hui.isoformat(),
        "periode_analysee_jours": PERIODE_ANALYSE_JOURS,
        "nb_commandes": len(commandes),
    }
    if not commandes:
        resultat["message"] = "Aucune commande sur la période analysée."
        return resultat

    montants = [c.montant_ht for c in commandes]
    dates = sorted({c.date for c in commandes})
    intervalle = _intervalle_median(dates)

    # Jours de commande habituels : ceux qui représentent au moins 20 % des commandes
    compte_jours = Counter(c.date.weekday() for c in commandes)
    jours_habituels = [
        JOURS_SEMAINE[j] for j, n in sorted(compte_jours.items()) if n / len(commandes) >= 0.20
    ]

    tendance = _tendance_ca(commandes, aujourd_hui)

    # Chiffre d'affaires mensuel (pour le graphique / le contexte)
    ca_mensuel: dict[str, float] = defaultdict(float)
    for c in commandes:
        ca_mensuel[c.date.strftime("%Y-%m")] += c.montant_ht

    # Répartition par catégorie
    ca_categorie: dict[str, float] = defaultdict(float)
    for c in commandes:
        for l in c.lignes:
            categorie = catalogue[l.produit_code].categorie if l.produit_code in catalogue else "Autre"
            ca_categorie[categorie] += l.quantite * l.prix_unitaire_ht
    total = sum(ca_categorie.values()) or 1

    recurrents = _produits_recurrents(commandes)
    produits_recurrents = sorted(
        (
            {
                "code": code,
                "libelle": catalogue[code].libelle if code in catalogue else code,
                "unite": catalogue[code].unite if code in catalogue else "",
                "frequence_pct": round(info["frequence"] * 100),
                "nb_commandes": info["nb_commandes"],
                "quantite_habituelle": info["quantite_habituelle"],
                "derniere_commande": info["dates"][-1].isoformat(),
            }
            for code, info in recurrents.items()
        ),
        key=lambda p: (-p["frequence_pct"], p["code"]),
    )

    resultat.update(
        {
            "premiere_commande": dates[0].isoformat(),
            "derniere_commande": dates[-1].isoformat(),
            "jours_depuis_derniere_commande": (aujourd_hui - dates[-1]).days,
            "intervalle_median_jours": intervalle,
            "commandes_par_semaine": _arrondi(len(commandes) / (PERIODE_ANALYSE_JOURS / 7)),
            "jours_habituels": jours_habituels,
            "prochain_jour_habituel": _prochain_jour(aujourd_hui, jours_habituels),
            "panier_moyen_ht": round(sum(montants) / len(montants), 2),
            "ca_total_ht": round(sum(montants), 2),
            "tendance_ca_pct": tendance,
            "ca_mensuel_ht": {m: round(v, 2) for m, v in sorted(ca_mensuel.items())},
            "repartition_categories_pct": {
                k: round(v / total * 100) for k, v in sorted(ca_categorie.items(), key=lambda kv: -kv[1])
            },
            "produits_recurrents": produits_recurrents,
        }
    )
    return resultat


def _tendance_ca(commandes: list[Commande], aujourd_hui: date, semaines: int = 12) -> int | None:
    """Évolution (en %) du CA moyen par semaine d'activité : 12 dernières semaines vs 12 précédentes.

    On ne compte que les semaines où le client a commandé, pour ne pas confondre
    une fermeture (vacances scolaires, congés annuels) avec une baisse d'activité.
    """
    limite = aujourd_hui - timedelta(weeks=semaines)
    debut = limite - timedelta(weeks=semaines)

    def ca_moyen_hebdo(cmds: list[Commande]) -> float | None:
        semaines_actives = {c.date.isocalendar()[:2] for c in cmds}
        return sum(c.montant_ht for c in cmds) / len(semaines_actives) if semaines_actives else None

    recent = ca_moyen_hebdo([c for c in commandes if c.date >= limite])
    ancien = ca_moyen_hebdo([c for c in commandes if debut <= c.date < limite])
    if not recent or not ancien:
        return None
    return round((recent - ancien) / ancien * 100)


def _prochain_jour(aujourd_hui: date, jours_habituels: list[str]) -> str | None:
    """Prochain jour habituel de commande à partir de demain."""
    if not jours_habituels:
        return None
    indices = {JOURS_SEMAINE.index(j) for j in jours_habituels}
    for decalage in range(1, 8):
        jour = aujourd_hui + timedelta(days=decalage)
        if jour.weekday() in indices:
            return f"{JOURS_SEMAINE[jour.weekday()]} {jour:%d/%m}"
    return None


# ---------------------------------------------------------------------------
# Outil 2 : produits habituels pas encore commandés sur la période en cours
# ---------------------------------------------------------------------------


def produits_habituels_manquants(source: DataSource, client_id: str) -> dict[str, Any]:
    """Produits habituels du client qu'il n'a pas commandés depuis plus longtemps que d'habitude.

    La « période en cours » est propre à chaque produit : c'est son rythme
    habituel d'achat chez ce client. Un produit est signalé quand il n'a pas été
    commandé depuis plus de 1,5 fois ce rythme (et au moins 7 jours).
    Au-delà de 3 fois le rythme, il est marqué « décroché » : le client l'achète
    probablement ailleurs, c'est un point de vigilance commerciale.
    """
    source.get_client(client_id)  # vérifie l'existence du client
    aujourd_hui = source.date_du_jour()
    commandes = _historique(source, client_id)
    catalogue = _catalogue(source)

    manquants = []
    for code, info in _produits_recurrents(commandes).items():
        rythme = _intervalle_median(info["dates"])
        if rythme is None:
            continue
        derniere = info["dates"][-1]
        jours_depuis = (aujourd_hui - derniere).days
        seuil = max(RETARD_MINIMUM_JOURS, rythme * FACTEUR_RETARD)
        if jours_depuis <= seuil:
            continue
        produit = catalogue.get(code)
        manquants.append(
            {
                "code": code,
                "libelle": produit.libelle if produit else code,
                "unite": produit.unite if produit else "",
                "prix_unitaire_ht": produit.prix_unitaire_ht if produit else None,
                "frequence_pct": round(info["frequence"] * 100),
                "rythme_habituel_jours": rythme,
                "derniere_commande": derniere.isoformat(),
                "jours_depuis_derniere_commande": jours_depuis,
                "quantite_habituelle": info["quantite_habituelle"],
                "retard_ratio": round(jours_depuis / rythme, 1),
                "statut": "décroché" if jours_depuis > rythme * FACTEUR_DECROCHAGE else "en retard",
            }
        )

    # Les plus importants d'abord : fréquence d'achat élevée et retard marqué
    manquants.sort(key=lambda m: (-(m["frequence_pct"] * min(m["retard_ratio"], 5)), m["code"]))
    return {
        "client_id": client_id,
        "date_du_jour": aujourd_hui.isoformat(),
        "regle": (
            f"Produit présent dans au moins {int(SEUIL_PRODUIT_RECURRENT * 100)} % des commandes, "
            f"non commandé depuis plus de {FACTEUR_RETARD} × son rythme habituel "
            f"(minimum {RETARD_MINIMUM_JOURS} jours)."
        ),
        "produits": manquants,
    }


# ---------------------------------------------------------------------------
# Outil 3 : stock à écouler (DLC courte ou surstock), pertinent pour le client
# ---------------------------------------------------------------------------


def seuil_dlc_courte(produit: Produit) -> int:
    """Nombre de jours avant DLC en dessous duquel un lot est « à DLC courte ».

    Frais : 30 % de la durée de vie du produit, entre 2 et 5 jours (un poisson
    qui se garde 5 jours n'est pas « court » à J+4, un fromage l'est).
    Surgelé : 30 jours.
    """
    if produit.famille == "surgele":
        return DLC_COURTE_SURGELE_JOURS
    return max(2, min(5, round(produit.duree_vie_jours * 0.3)))


def remise_suggeree(famille: str, jours_avant_dlc: int | None, couverture_jours: float | None,
                    dlc_courte: bool = True) -> int:
    """Remise suggérée (en %) selon l'urgence d'écoulement. Plafonnée à 30 %.

    `dlc_courte` indique si le lot est sous le seuil de DLC courte (voir `seuil_dlc_courte`).
    - DLC courte (frais) : 30 % à J+1, 25 % à J+2, 20 % à J+3, 15 % à J+4/J+5.
    - DLC courte (surgelé, ≤ 30 j) : 15 %, ou 20 % à 15 jours et moins.
    - Surstock : 10 %, ou 15 % si la couverture dépasse 2 × le seuil de surstock.
    On retient la plus forte des remises applicables.
    """
    remise = 0
    if dlc_courte and jours_avant_dlc is not None:
        if famille == "frais":
            remise = {1: 30, 2: 25, 3: 20}.get(jours_avant_dlc, 15)
        else:
            remise = 20 if jours_avant_dlc <= 15 else 15
    seuil = SEUIL_SURSTOCK_JOURS[famille]
    if couverture_jours is not None and couverture_jours > seuil:
        remise = max(remise, 15 if couverture_jours > 2 * seuil else 10)
    return min(remise, REMISE_MAX_PCT)


def _situations_stock(source: DataSource) -> list[dict[str, Any]]:
    """Tous les produits en stock qui nécessitent d'être écoulés, tous clients confondus."""
    aujourd_hui = source.date_du_jour()
    catalogue = _catalogue(source)

    # Rotation : quantité vendue par jour sur la fenêtre récente, tous clients
    ventes: dict[str, float] = defaultdict(float)
    for cmd in source.get_order_history(depuis=aujourd_hui - timedelta(days=FENETRE_ROTATION_JOURS)):
        for l in cmd.lignes:
            ventes[l.produit_code] += l.quantite

    lots_par_produit = defaultdict(list)
    for lot in source.get_stock():
        # Un lot qui expire aujourd'hui ou avant ne peut plus être livré : exclu.
        if (lot.dlc - aujourd_hui).days >= 1 and lot.quantite > 0:
            lots_par_produit[lot.produit_code].append(lot)

    situations = []
    for code, lots in lots_par_produit.items():
        produit = catalogue.get(code)
        if produit is None:
            continue
        lots.sort(key=lambda l: l.dlc)
        stock_total = sum(l.quantite for l in lots)
        par_jour = ventes[code] / FENETRE_ROTATION_JOURS
        couverture = round(stock_total / par_jour, 1) if par_jour > 0 else None
        # Le lot à pousser en priorité est celui dont la DLC est la plus proche
        lot = lots[0]
        jours_dlc = (lot.dlc - aujourd_hui).days

        motifs = []
        dlc_courte = jours_dlc <= seuil_dlc_courte(produit)
        if dlc_courte:
            motifs.append("DLC courte")
        # Sans aucune vente récente, tout stock est considéré comme dormant
        if couverture is None or couverture > SEUIL_SURSTOCK_JOURS[produit.famille]:
            motifs.append("surstock")
        if not motifs:
            continue

        remise = remise_suggeree(
            produit.famille, jours_dlc, couverture if couverture is not None else float("inf"), dlc_courte
        )
        situations.append(
            {
                "code": code,
                "libelle": produit.libelle,
                "categorie": produit.categorie,
                "famille": produit.famille,
                "unite": produit.unite,
                "motifs": motifs,
                "lot_id": lot.id,
                "quantite_lot": lot.quantite,
                "dlc": lot.dlc.isoformat(),
                "jours_avant_dlc": jours_dlc,
                "stock_total": stock_total,
                "couverture_jours": couverture,
                "prix_unitaire_ht": produit.prix_unitaire_ht,
                "remise_suggeree_pct": remise,
                "prix_remise_ht": round(produit.prix_unitaire_ht * (1 - remise / 100), 2),
            }
        )
    return situations


def stock_a_ecouler(source: DataSource, client_id: str, limite: int = 6) -> dict[str, Any]:
    """Produits à écouler (DLC courte ou surstock) pertinents pour ce client, avec remise suggérée.

    Pertinence pour le client (du plus au moins pertinent) :
    3 = produit qu'il achète régulièrement ; 2 = produit qu'il a déjà acheté ;
    1 = produit acheté par d'autres clients du même type. Sinon : non proposé.
    """
    client = source.get_client(client_id)
    commandes = _historique(source, client_id)
    recurrents = _produits_recurrents(commandes)
    achetes = _dates_par_produit(commandes)

    # Produits achetés par les clients du même type (au moins 2 fois)
    similaires = _clients_similaires(source, client_id, client.type)
    adoption = _adoption_par_produit(source, similaires)

    propositions = []
    for s in _situations_stock(source):
        code = s["code"]
        if code in recurrents:
            pertinence, raison = 3, f"produit acheté régulièrement ({len(achetes[code])} commandes sur 6 mois)"
        elif code in achetes:
            pertinence, raison = 2, f"déjà acheté {len(achetes[code])} fois sur 6 mois"
        elif adoption.get(code, 0) >= min(2, len(similaires)) > 0:
            n = adoption[code]
            pertinence, raison = 1, f"acheté par {n} autre(s) client(s) de type « {client.type} »"
        else:
            continue
        urgence = 2 if "DLC courte" in s["motifs"] else 1
        propositions.append({**s, "pertinence": pertinence, "raison_pertinence": raison, "_tri": (pertinence, urgence)})

    propositions.sort(key=lambda p: (-p["_tri"][0], -p["_tri"][1], p["jours_avant_dlc"], p["code"]))
    for p in propositions:
        del p["_tri"]
    return {
        "client_id": client_id,
        "date_du_jour": source.date_du_jour().isoformat(),
        "regle_remise": (
            "DLC courte frais : 30 % à J+1, 25 % à J+2, 20 % à J+3, 15 % au-delà. Surgelé ≤ 30 j : 15-20 %. "
            "Surstock : 10-15 %. Plafond 30 %. La remise suggérée est un maximum."
        ),
        "produits": propositions[:limite],
    }


# ---------------------------------------------------------------------------
# Outil 4 : suggestions croisées (ce qu'achètent les clients similaires)
# ---------------------------------------------------------------------------


def _clients_similaires(source: DataSource, client_id: str, type_client: str) -> list[str]:
    return [c.id for c in source.get_clients() if c.type == type_client and c.id != client_id]


def _adoption_par_produit(source: DataSource, clients: list[str]) -> dict[str, int]:
    """Nombre de clients (parmi `clients`) ayant acheté chaque produit au moins 2 fois."""
    debut = source.date_du_jour() - timedelta(days=PERIODE_ANALYSE_JOURS)
    cibles = set(clients)
    achats: dict[str, Counter] = defaultdict(Counter)
    for cmd in source.get_order_history(depuis=debut):
        if cmd.client_id in cibles:
            for l in {l.produit_code for l in cmd.lignes}:
                achats[l][cmd.client_id] += 1
    return {code: sum(1 for n in compte.values() if n >= 2) for code, compte in achats.items()}


def suggestions_croisees(source: DataSource, client_id: str, limite: int = 5) -> dict[str, Any]:
    """Produits jamais achetés par le client mais adoptés par les clients du même type.

    Exemple : « 3 boulangeries sur 4 achètent aussi le pain aux raisins cru ».
    """
    client = source.get_client(client_id)
    catalogue = _catalogue(source)
    deja_achetes = set(_dates_par_produit(_historique(source, client_id)))
    similaires = _clients_similaires(source, client_id, client.type)
    if not similaires:
        return {"client_id": client_id, "type_client": client.type, "nb_clients_similaires": 0, "produits": []}

    adoption = _adoption_par_produit(source, similaires)
    codes_a_ecouler = {s["code"] for s in _situations_stock(source)}
    suggestions = []
    for code, n in adoption.items():
        taux = n / len(similaires)
        if code in deja_achetes or code not in catalogue or taux < 0.5 or n < min(2, len(similaires)):
            continue
        p = catalogue[code]
        suggestions.append(
            {
                "code": code,
                "libelle": p.libelle,
                "categorie": p.categorie,
                "unite": p.unite,
                "prix_unitaire_ht": p.prix_unitaire_ht,
                "nb_clients_similaires_acheteurs": n,
                "taux_adoption_pct": round(taux * 100),
                "en_stock_a_ecouler": code in codes_a_ecouler,
            }
        )
    suggestions.sort(key=lambda s: (-s["taux_adoption_pct"], not s["en_stock_a_ecouler"], s["code"]))
    return {
        "client_id": client_id,
        "type_client": client.type,
        "nb_clients_similaires": len(similaires),
        "produits": suggestions[:limite],
    }


# ---------------------------------------------------------------------------
# Exposition des outils à Claude (schémas JSON) et exécution
# ---------------------------------------------------------------------------

_SCHEMA_CLIENT = {
    "type": "object",
    "properties": {"client_id": {"type": "string", "description": "Identifiant du client, ex. C001"}},
    "required": ["client_id"],
    "additionalProperties": False,
}

DEFINITIONS_OUTILS = [
    {
        "name": "historique_client",
        "description": (
            "Habitudes d'achat du client sur 6 mois : fiche client, nombre de commandes, fréquence, "
            "jours habituels de commande, panier moyen HT, tendance du chiffre d'affaires, "
            "répartition par catégorie et produits récurrents."
        ),
        "input_schema": _SCHEMA_CLIENT,
        "strict": True,
    },
    {
        "name": "produits_habituels_manquants",
        "description": (
            "Produits habituels du client qu'il n'a pas commandés depuis plus longtemps que son rythme "
            "habituel. Statut « décroché » = probable achat chez un concurrent."
        ),
        "input_schema": _SCHEMA_CLIENT,
        "strict": True,
    },
    {
        "name": "stock_a_ecouler",
        "description": (
            "Produits en stock à écouler (DLC courte ou surstock) pertinents pour ce client, avec le lot "
            "prioritaire, la DLC et la remise suggérée (qui est un maximum à ne pas dépasser)."
        ),
        "input_schema": _SCHEMA_CLIENT,
        "strict": True,
    },
    {
        "name": "suggestions_croisees",
        "description": (
            "Produits jamais achetés par ce client mais adoptés par au moins la moitié des clients "
            "du même type (restaurants, boulangeries…)."
        ),
        "input_schema": _SCHEMA_CLIENT,
        "strict": True,
    },
]

FONCTIONS_OUTILS = {
    "historique_client": historique_client,
    "produits_habituels_manquants": produits_habituels_manquants,
    "stock_a_ecouler": stock_a_ecouler,
    "suggestions_croisees": suggestions_croisees,
}


def executer_outil(source: DataSource, nom: str, arguments: dict[str, Any]) -> dict[str, Any]:
    """Exécute un outil métier par son nom (appelé par la boucle de l'agent)."""
    if nom not in FONCTIONS_OUTILS:
        raise ValueError(f"Outil inconnu : {nom}")
    return FONCTIONS_OUTILS[nom](source, arguments["client_id"])


def contexte_complet(source: DataSource, client_id: str) -> dict[str, Any]:
    """Résultats des quatre outils pour un client (utilisé par le mode repli et la validation)."""
    return {nom: fonction(source, client_id) for nom, fonction in FONCTIONS_OUTILS.items()}


__all__ = [
    "DEFINITIONS_OUTILS",
    "contexte_complet",
    "executer_outil",
    "historique_client",
    "produits_habituels_manquants",
    "remise_suggeree",
    "stock_a_ecouler",
    "suggestions_croisees",
]
