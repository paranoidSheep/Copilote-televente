"""Indicateurs d'efficacité calculés à partir des comptes-rendus d'appels."""

from __future__ import annotations

from collections import Counter, defaultdict
from collections.abc import Sequence
from datetime import date

from pydantic import BaseModel, ConfigDict

from .modeles import CompteRendu, Issue, Origine, Reponse


class _Stat(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid", json_schema_serialization_defaults_required=True)


class StatOrigine(_Stat):
    origine: Origine
    proposes: int
    acceptes: int
    taux_acceptation_pct: int | None
    ca_accepte_ht: float


class StatTelevendeur(_Stat):
    televendeur: str
    appels: int
    commandes: int
    ca_accepte_ht: float


class StatJour(_Stat):
    jour: date
    appels: int
    ca_accepte_ht: float


class StatProduit(_Stat):
    code: str
    libelle: str
    proposes: int
    acceptes: int


class StatistiquesAppels(_Stat):
    nb_appels: int
    nb_clients: int
    issues: dict[Issue, int]
    taux_transformation_pct: int | None  # appels aboutissant à une commande
    ca_accepte_ht: float
    quantite_stock_ecoulee: float
    par_origine: list[StatOrigine]
    par_televendeur: list[StatTelevendeur]
    par_jour: list[StatJour]
    produits_les_plus_acceptes: list[StatProduit]


def _taux(numerateur: int, denominateur: int) -> int | None:
    return round(numerateur / denominateur * 100) if denominateur else None


def calculer_statistiques(comptes_rendus: Sequence[CompteRendu]) -> StatistiquesAppels:
    issues = Counter(cr.issue for cr in comptes_rendus)
    lignes = [l for cr in comptes_rendus for l in cr.lignes]

    par_origine = []
    for origine in Origine:
        concernees = [l for l in lignes if l.origine is origine]
        if not concernees:
            continue
        acceptees = [l for l in concernees if l.reponse is Reponse.ACCEPTE]
        par_origine.append(
            StatOrigine(
                origine=origine,
                proposes=len(concernees),
                acceptes=len(acceptees),
                taux_acceptation_pct=_taux(len(acceptees), len(concernees)),
                ca_accepte_ht=round(sum(l.montant_ht for l in acceptees), 2),
            )
        )

    vendeurs: dict[str, list[CompteRendu]] = defaultdict(list)
    jours: dict[date, list[CompteRendu]] = defaultdict(list)
    for cr in comptes_rendus:
        vendeurs[cr.televendeur].append(cr)
        jours[cr.cree_le.date()].append(cr)

    produits: dict[str, tuple[str, int, int]] = {}
    for l in lignes:
        libelle, proposes, acceptes = produits.get(l.code, (l.libelle, 0, 0))
        produits[l.code] = (libelle, proposes + 1, acceptes + (l.reponse is Reponse.ACCEPTE))

    return StatistiquesAppels(
        nb_appels=len(comptes_rendus),
        nb_clients=len({cr.client_id for cr in comptes_rendus}),
        issues={issue: issues.get(issue, 0) for issue in Issue},
        taux_transformation_pct=_taux(issues.get(Issue.COMMANDE, 0), len(comptes_rendus)),
        ca_accepte_ht=round(sum(cr.montant_accepte_ht for cr in comptes_rendus), 2),
        quantite_stock_ecoulee=sum(
            l.quantite for l in lignes if l.origine is Origine.STOCK and l.reponse is Reponse.ACCEPTE
        ),
        par_origine=par_origine,
        par_televendeur=sorted(
            (
                StatTelevendeur(
                    televendeur=nom,
                    appels=len(crs),
                    commandes=sum(cr.issue is Issue.COMMANDE for cr in crs),
                    ca_accepte_ht=round(sum(cr.montant_accepte_ht for cr in crs), 2),
                )
                for nom, crs in vendeurs.items()
            ),
            key=lambda s: -s.ca_accepte_ht,
        ),
        par_jour=[
            StatJour(
                jour=jour,
                appels=len(crs),
                ca_accepte_ht=round(sum(cr.montant_accepte_ht for cr in crs), 2),
            )
            for jour, crs in sorted(jours.items())
        ],
        produits_les_plus_acceptes=sorted(
            (StatProduit(code=c, libelle=lib, proposes=p, acceptes=a) for c, (lib, p, a) in produits.items()),
            key=lambda s: (-s.acceptes, -s.proposes, s.code),
        )[:10],
    )
