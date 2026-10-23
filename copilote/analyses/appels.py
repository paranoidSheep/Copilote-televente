"""Résumé des appels précédents d'un client (à partir du journal)."""

from __future__ import annotations

from collections.abc import Sequence
from datetime import date, timedelta

from copilote.journal import CompteRendu, Issue, Origine, Reponse

from .base import Resultat
from .regles import ReglesMetier

OFFRES = frozenset({Origine.STOCK, Origine.SUGGESTION})


class AppelPrecedent(Resultat):
    jour: date
    televendeur: str
    issue: Issue
    notes: str
    rappel_le: date | None
    produits_acceptes: list[str]
    produits_refuses: list[str]


class HistoriqueAppels(Resultat):
    client_id: str
    appels: list[AppelPrecedent]
    codes_refuses_recemment: list[str]  # offres (stock, suggestions) refusées : à ne pas reproposer tout de suite
    rappel_prevu: date | None  # rappel demandé par le client, s'il est encore à venir ou dû


def resumer_appels(
    comptes_rendus: Sequence[CompteRendu],
    client_id: str,
    aujourd_hui: date,
    regles: ReglesMetier,
    limite: int = 5,
) -> HistoriqueAppels:
    """Derniers appels du client, offres refusées récemment et rappel en attente.

    Seules les offres (stock à écouler, suggestions) refusées sont mémorisées : un
    produit habituel non commandé lors d'un appel reste un produit habituel.
    """
    du_client = sorted(
        (cr for cr in comptes_rendus if cr.client_id == client_id), key=lambda cr: cr.cree_le, reverse=True
    )
    limite_refus = aujourd_hui - timedelta(days=regles.jours_memoire_refus)
    refuses = sorted(
        {
            l.code
            for cr in du_client
            if cr.cree_le.date() >= limite_refus
            for l in cr.lignes
            if l.reponse is Reponse.REFUSE and l.origine in OFFRES
        }
    )
    # Le rappel compte s'il a été demandé lors du DERNIER appel (sinon il a été traité depuis)
    dernier = du_client[0] if du_client else None
    rappel = dernier.rappel_le if dernier is not None and dernier.issue is Issue.RAPPELER else None

    return HistoriqueAppels(
        client_id=client_id,
        appels=[
            AppelPrecedent(
                jour=cr.cree_le.date(),
                televendeur=cr.televendeur,
                issue=cr.issue,
                notes=cr.notes,
                rappel_le=cr.rappel_le,
                produits_acceptes=[l.libelle for l in cr.lignes if l.reponse is Reponse.ACCEPTE],
                produits_refuses=[l.libelle for l in cr.lignes if l.reponse is Reponse.REFUSE],
            )
            for cr in du_client[:limite]
        ],
        codes_refuses_recemment=refuses,
        rappel_prevu=rappel,
    )
