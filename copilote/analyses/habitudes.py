"""Analyse des habitudes d'achat d'un client."""

from __future__ import annotations

from collections import defaultdict
from datetime import date

from copilote.domaine import Client

from .base import Resultat
from .referentiel import Referentiel
from .statistiques import (
    JourSemaine,
    intervalle_median,
    jours_habituels,
    prochain_jour,
    tendance_ca,
)


class ProduitRecurrent(Resultat):
    code: str
    libelle: str
    unite: str
    frequence_pct: int
    nb_commandes: int
    quantite_habituelle: float
    derniere_commande: date


class CaMensuel(Resultat):
    mois: str  # AAAA-MM
    ca_ht: float


class PartCategorie(Resultat):
    categorie: str
    part_pct: int


class HabitudesClient(Resultat):
    client: Client
    date_du_jour: date
    periode_analysee_jours: int
    nb_commandes: int
    premiere_commande: date | None = None
    derniere_commande: date | None = None
    jours_depuis_derniere_commande: int | None = None
    intervalle_median_jours: float | None = None
    commandes_par_semaine: float = 0.0
    jours_habituels: list[JourSemaine] = []
    prochain_jour_habituel: date | None = None
    panier_moyen_ht: float | None = None
    ca_total_ht: float = 0.0
    tendance_ca_pct: int | None = None
    ca_mensuel: list[CaMensuel] = []
    repartition_categories: list[PartCategorie] = []
    produits_recurrents: list[ProduitRecurrent] = []


def analyser_habitudes(ref: Referentiel, client_id: str) -> HabitudesClient:
    """Résumé chiffré des habitudes d'achat d'un client sur la période analysée."""
    client = ref.client(client_id)
    commandes = ref.commandes_client(client_id)
    regles = ref.regles
    base = HabitudesClient(
        client=client,
        date_du_jour=ref.date_du_jour,
        periode_analysee_jours=regles.periode_analyse_jours,
        nb_commandes=len(commandes),
    )
    if not commandes:
        return base

    dates = sorted({c.date for c in commandes})
    jours = jours_habituels(commandes, regles)

    ca_mois: dict[str, float] = defaultdict(float)
    ca_categories: dict[str, float] = defaultdict(float)
    for commande in commandes:
        ca_mois[commande.date.strftime("%Y-%m")] += commande.montant_ht
        for ligne in commande.lignes:
            categorie = ref.produits[ligne.produit_code].categorie if ligne.produit_code in ref.produits else "Autre"
            ca_categories[categorie] += ligne.montant_ht
    total_categories = sum(ca_categories.values()) or 1.0
    ca_total = sum(c.montant_ht for c in commandes)

    recurrents = sorted(
        (
            ProduitRecurrent(
                code=r.code,
                libelle=ref.produits[r.code].libelle if r.code in ref.produits else r.code,
                unite=ref.produits[r.code].unite if r.code in ref.produits else "",
                frequence_pct=round(r.frequence * 100),
                nb_commandes=r.nb_commandes,
                quantite_habituelle=r.quantite_habituelle,
                derniere_commande=r.derniere_commande,
            )
            for r in ref.produits_recurrents(client_id).values()
        ),
        key=lambda p: (-p.frequence_pct, p.code),
    )

    return base.model_copy(
        update={
            "premiere_commande": dates[0],
            "derniere_commande": dates[-1],
            "jours_depuis_derniere_commande": (ref.date_du_jour - dates[-1]).days,
            "intervalle_median_jours": intervalle_median(dates),
            "commandes_par_semaine": round(len(commandes) / (regles.periode_analyse_jours / 7), 1),
            "jours_habituels": jours,
            "prochain_jour_habituel": prochain_jour(ref.date_du_jour, jours),
            "panier_moyen_ht": round(ca_total / len(commandes), 2),
            "ca_total_ht": round(ca_total, 2),
            "tendance_ca_pct": tendance_ca(commandes, ref.date_du_jour, regles.semaines_tendance),
            "ca_mensuel": [CaMensuel(mois=m, ca_ht=round(v, 2)) for m, v in sorted(ca_mois.items())],
            "repartition_categories": [
                PartCategorie(categorie=k, part_pct=round(v / total_categories * 100))
                for k, v in sorted(ca_categories.items(), key=lambda kv: -kv[1])
            ],
            "produits_recurrents": recurrents,
        }
    )
