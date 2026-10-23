"""Fixtures partagées : une petite source de données « à la main » et le mock complet."""

from __future__ import annotations

from datetime import date, timedelta

import pytest

from datahub.base import Client, ClientIntrouvable, Commande, DataSource, LigneCommande, Lot, Produit
from datahub.mock import MockDataSource

AUJOURD_HUI = date(2026, 10, 23)


class SourceMinimale(DataSource):
    """Source en mémoire, construite dans chaque test pour des assertions exactes."""

    nom = "test"

    def __init__(self, clients, produits, commandes, lots):
        self.clients = {c.id: c for c in clients}
        self.produits = produits
        self.commandes = sorted(commandes, key=lambda c: c.date)
        self.lots = lots

    def get_clients(self):
        return list(self.clients.values())

    def get_client(self, client_id):
        if client_id not in self.clients:
            raise ClientIntrouvable(client_id)
        return self.clients[client_id]

    def get_order_history(self, client_id=None, depuis=None):
        return [
            c for c in self.commandes
            if (client_id is None or c.client_id == client_id) and (depuis is None or c.date >= depuis)
        ]

    def get_products(self):
        return self.produits

    def get_stock(self):
        return self.lots

    def date_du_jour(self):
        return AUJOURD_HUI


def client(id_, type_="Restaurant"):
    return Client(id=id_, nom=f"Client {id_}", type=type_, ville="Lyon", contact="M. Test",
                  telephone="04 00 00 00 00", commercial="Julie")


def produit(code, famille="frais", prix=10.0, duree_vie=10, categorie="Crèmerie"):
    return Produit(code=code, libelle=f"Produit {code}", categorie=categorie, famille=famille,
                   unite="kg", prix_unitaire_ht=prix, duree_vie_jours=duree_vie)


def commande(id_, client_id, jours_avant, lignes):
    """`lignes` : liste de (code, quantité). Prix fixé à 10 €."""
    return Commande(
        id=id_, client_id=client_id, date=AUJOURD_HUI - timedelta(days=jours_avant),
        lignes=[LigneCommande(produit_code=c, quantite=q, prix_unitaire_ht=10.0) for c, q in lignes],
    )


def lot(id_, code, quantite, jours_avant_dlc):
    dlc = AUJOURD_HUI + timedelta(days=jours_avant_dlc)
    return Lot(id=id_, produit_code=code, quantite=quantite, dlc=dlc,
               date_reception=AUJOURD_HUI - timedelta(days=2), entrepot="Test")


@pytest.fixture(scope="session")
def mock_source() -> MockDataSource:
    return MockDataSource()


@pytest.fixture
def source_simple() -> SourceMinimale:
    """Un restaurant R1 qui commande chaque semaine depuis 10 semaines :
    - P1 à chaque commande (jusqu'à la semaine dernière) ;
    - P2 chaque semaine mais plus rien depuis 5 semaines (décroché) ;
    - P3 une seule fois (occasionnel).
    Deux autres restaurants (R2, R3) achètent P4, que R1 n'a jamais acheté.
    """
    commandes = []
    for semaine in range(1, 11):
        jours = 7 * semaine
        lignes = [("P1", 5)]
        if jours >= 35:
            lignes.append(("P2", 2))
        if semaine == 4:
            lignes.append(("P3", 1))
        commandes.append(commande(f"A{semaine}", "R1", jours, lignes))
    for i, cid in enumerate(("R2", "R3")):
        for semaine in range(1, 5):
            commandes.append(commande(f"{cid}-{semaine}", cid, 7 * semaine + i, [("P4", 3), ("P1", 1)]))

    produits = [
        produit("P1", duree_vie=10),
        produit("P2", duree_vie=10),
        produit("P3", duree_vie=10),
        produit("P4", duree_vie=10),
        produit("P5", duree_vie=10),  # jamais acheté par personne
        produit("S1", famille="surgele", duree_vie=365, categorie="Surgelés"),
    ]
    lots = [
        lot("L1", "P1", 20, 1),  # DLC demain : -30 %
        lot("L2", "P1", 10, 8),
        lot("L3", "P5", 50, 1),  # DLC courte mais pertinent pour personne
        lot("L4", "P4", 5, 0),  # expire aujourd'hui : non livrable, ignoré
        lot("L5", "P4", 5, 9),
    ]
    clients = [client("R1"), client("R2"), client("R3"), client("B1", "Boulangerie-pâtisserie")]
    return SourceMinimale(clients, produits, commandes, lots)
