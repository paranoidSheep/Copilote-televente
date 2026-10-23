"""Briques statistiques élémentaires, partagées par les analyses."""

from __future__ import annotations

from collections import defaultdict
from collections.abc import Iterable, Sequence
from dataclasses import dataclass
from datetime import date, timedelta
from enum import StrEnum
from statistics import median

from copilote.domaine import Commande

from .regles import ReglesMetier


class JourSemaine(StrEnum):
    LUNDI = "lundi"
    MARDI = "mardi"
    MERCREDI = "mercredi"
    JEUDI = "jeudi"
    VENDREDI = "vendredi"
    SAMEDI = "samedi"
    DIMANCHE = "dimanche"

    @classmethod
    def de(cls, jour: date) -> JourSemaine:
        return list(cls)[jour.weekday()]

    @property
    def indice(self) -> int:
        return list(JourSemaine).index(self)


@dataclass(frozen=True, slots=True)
class Recurrence:
    """Comment un client achète un produit donné."""

    code: str
    dates: tuple[date, ...]  # dates d'achat, triées, sans doublon
    frequence: float  # part des commandes du client contenant ce produit
    quantite_habituelle: float  # quantité médiane

    @property
    def nb_commandes(self) -> int:
        return len(self.dates)

    @property
    def derniere_commande(self) -> date:
        return self.dates[-1]

    @property
    def rythme_jours(self) -> float | None:
        return intervalle_median(self.dates)


def intervalle_median(dates: Sequence[date]) -> float | None:
    """Intervalle médian en jours entre deux dates successives.

    La médiane (plutôt que la moyenne) neutralise les longues interruptions
    ponctuelles : vacances scolaires, fermeture annuelle…
    """
    if len(dates) < 2:
        return None
    return float(median((b - a).days for a, b in zip(dates, dates[1:], strict=False)))


def recurrences(commandes: Sequence[Commande]) -> dict[str, Recurrence]:
    """Récurrence d'achat de chaque produit présent dans les commandes."""
    dates: dict[str, set[date]] = defaultdict(set)
    quantites: dict[str, list[float]] = defaultdict(list)
    for commande in commandes:
        for ligne in commande.lignes:
            dates[ligne.produit_code].add(commande.date)
            quantites[ligne.produit_code].append(ligne.quantite)
    nb = len(commandes)
    return {
        code: Recurrence(
            code=code,
            dates=tuple(sorted(d)),
            frequence=len(d) / nb,
            quantite_habituelle=round(median(quantites[code]), 1),
        )
        for code, d in dates.items()
    }


def produits_recurrents(commandes: Sequence[Commande], regles: ReglesMetier) -> dict[str, Recurrence]:
    """Produits présents dans une part significative des commandes du client."""
    if not commandes:
        return {}
    return {
        code: r
        for code, r in recurrences(commandes).items()
        if r.frequence >= regles.seuil_produit_recurrent and r.nb_commandes >= regles.min_commandes_recurrent
    }


def jours_habituels(commandes: Sequence[Commande], regles: ReglesMetier) -> list[JourSemaine]:
    """Jours de la semaine représentant une part significative des commandes."""
    if not commandes:
        return []
    compte: dict[JourSemaine, int] = defaultdict(int)
    for commande in commandes:
        compte[JourSemaine.de(commande.date)] += 1
    return sorted(
        (j for j, n in compte.items() if n / len(commandes) >= regles.seuil_jour_habituel),
        key=lambda j: j.indice,
    )


def prochain_jour(apres: date, jours: Iterable[JourSemaine]) -> date | None:
    """Prochaine date (strictement après `apres`) tombant un des jours donnés."""
    indices = {j.indice for j in jours}
    for decalage in range(1, 8):
        candidat = apres + timedelta(days=decalage)
        if candidat.weekday() in indices:
            return candidat
    return None


def tendance_ca(commandes: Sequence[Commande], aujourd_hui: date, semaines: int) -> int | None:
    """Évolution (%) du CA moyen par semaine d'activité : N dernières semaines vs N précédentes.

    Seules les semaines avec au moins une commande comptent : une fermeture
    (vacances, congés) n'est pas confondue avec une baisse d'activité.
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
