"""Plan d'écoulement : pour chaque produit à écouler, quels clients appeler."""

from __future__ import annotations

from datetime import date
from statistics import median

from .base import Resultat
from .referentiel import Referentiel
from .stock import Pertinence, SituationStock, evaluer_pertinence, situations_stock


class ClientCible(Resultat):
    client_id: str
    nom: str
    type: str
    commercial: str
    pertinence: Pertinence
    raison: str
    quantite_estimee: float  # quantité habituelle du client, ou quantité type du produit


class LigneEcoulement(Resultat):
    situation: SituationStock
    clients: list[ClientCible]
    quantite_potentielle: float
    couverture_plan_pct: int  # part du lot prioritaire que les clients ciblés pourraient absorber
    valeur_lot_ht: float


class PlanEcoulement(Resultat):
    date_du_jour: date
    lignes: list[LigneEcoulement]
    valeur_a_risque_ht: float  # valeur des lots à DLC courte
    nb_lots_urgents: int


def _quantite_type(ref: Referentiel, code: str) -> float:
    """Quantité médiane commandée pour ce produit, tous acheteurs confondus."""
    habitudes = [
        r.quantite_habituelle
        for client_id in ref.achats_par_produit_et_client.get(code, {})
        if (r := ref.recurrences(client_id).get(code)) is not None
    ]
    return round(median(habitudes), 1) if habitudes else 1.0


def construire_plan_ecoulement(ref: Referentiel, max_clients: int = 8) -> PlanEcoulement:
    lignes: list[LigneEcoulement] = []
    for situation in situations_stock(ref):
        quantite_type = _quantite_type(ref, situation.code)
        cibles: list[ClientCible] = []
        for client in ref.clients.values():
            pertinence, raison = evaluer_pertinence(ref, client.id, situation.code)
            if pertinence is Pertinence.AUCUNE:
                continue
            recurrence = ref.recurrences(client.id).get(situation.code)
            cibles.append(
                ClientCible(
                    client_id=client.id,
                    nom=client.nom,
                    type=client.type,
                    commercial=client.commercial,
                    pertinence=pertinence,
                    raison=raison,
                    quantite_estimee=recurrence.quantite_habituelle if recurrence else quantite_type,
                )
            )
        cibles.sort(key=lambda c: (-c.pertinence, -c.quantite_estimee, c.nom))
        cibles = cibles[:max_clients]
        potentiel = round(sum(c.quantite_estimee for c in cibles), 1)
        lignes.append(
            LigneEcoulement(
                situation=situation,
                clients=cibles,
                quantite_potentielle=potentiel,
                couverture_plan_pct=min(100, round(potentiel / situation.quantite_lot * 100))
                if situation.quantite_lot
                else 100,
                valeur_lot_ht=round(situation.quantite_lot * situation.prix_unitaire_ht, 2),
            )
        )
    urgentes = [l for l in lignes if l.situation.urgent]
    return PlanEcoulement(
        date_du_jour=ref.date_du_jour,
        lignes=lignes,
        valeur_a_risque_ht=round(sum(l.valeur_lot_ht for l in urgentes), 2),
        nb_lots_urgents=len(urgentes),
    )
