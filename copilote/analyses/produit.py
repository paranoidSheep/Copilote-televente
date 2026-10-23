"""Détail d'un produit vu depuis un client : achats, stock, pertinence."""

from __future__ import annotations

from datetime import date

from copilote.domaine import Produit

from .base import Resultat
from .referentiel import Referentiel
from .stock import Pertinence, SituationStock, evaluer_pertinence, nb_clients_similaires_acheteurs, situations_stock


class AchatClient(Resultat):
    date: date
    quantite: float


class LotDisponible(Resultat):
    id: str
    quantite: float
    dlc: date
    jours_avant_dlc: int


class DetailsProduit(Resultat):
    produit: Produit
    client_id: str
    nb_commandes_client: int
    quantite_habituelle: float | None
    rythme_jours: float | None
    derniers_achats: list[AchatClient]
    lots: list[LotDisponible]
    situation_stock: SituationStock | None
    pertinence: Pertinence
    raison_pertinence: str
    nb_clients_similaires_acheteurs: int
    ventes_journalieres: float


def analyser_produit(ref: Referentiel, client_id: str, code: str) -> DetailsProduit:
    """Tout ce qu'il faut savoir sur un produit pour en parler à ce client."""
    produit = ref.produit(code)
    recurrence = ref.recurrences(client_id).get(code)
    achats = [
        AchatClient(date=commande.date, quantite=ligne.quantite)
        for commande in ref.commandes_client(client_id)
        for ligne in commande.lignes
        if ligne.produit_code == code
    ]
    pertinence, raison = evaluer_pertinence(ref, client_id, code)
    return DetailsProduit(
        produit=produit,
        client_id=client_id,
        nb_commandes_client=recurrence.nb_commandes if recurrence else 0,
        quantite_habituelle=recurrence.quantite_habituelle if recurrence else None,
        rythme_jours=recurrence.rythme_jours if recurrence else None,
        derniers_achats=achats[-8:],
        lots=sorted(
            (
                LotDisponible(
                    id=lot.id, quantite=lot.quantite, dlc=lot.dlc, jours_avant_dlc=(lot.dlc - ref.date_du_jour).days
                )
                for lot in ref.lots
                if lot.produit_code == code and lot.dlc > ref.date_du_jour and lot.quantite > 0
            ),
            key=lambda l: l.dlc,
        ),
        situation_stock=next((s for s in situations_stock(ref) if s.code == code), None),
        pertinence=pertinence,
        raison_pertinence=raison,
        nb_clients_similaires_acheteurs=nb_clients_similaires_acheteurs(ref, client_id, code),
        ventes_journalieres=round(ref.ventes_journalieres.get(code, 0.0), 2),
    )
