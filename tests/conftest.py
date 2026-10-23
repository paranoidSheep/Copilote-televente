"""Fixtures partagées : une petite source « à la main » (assertions exactes) et le mock complet."""

from __future__ import annotations

import socket
import threading
import time
from collections.abc import Iterable, Iterator
from datetime import date, datetime, timedelta

import pytest
import uvicorn
from fastapi import FastAPI
from fastapi.testclient import TestClient

from copilote.analyses import Referentiel
from copilote.api import creer_app
from copilote.application import Application, creer_application
from copilote.comptes import DepotUtilisateursMemoire, Role, Utilisateur, mots_de_passe
from copilote.config import Config, ConfigSecurite, ModeLLM
from copilote.datahub import DataSource
from copilote.datahub.mock import MockDataSource
from copilote.datahub.simulateur import creer_simulateur
from copilote.domaine import Client, ClientIntrouvable, Commande, Famille, LigneCommande, Lot, Produit
from copilote.evaluation import DepotEvaluationsMemoire
from copilote.horloge import HorlogeFixe
from copilote.journal import DepotMemoire

AUJOURD_HUI = date(2026, 10, 23)  # un vendredi


class SourceMinimale(DataSource):
    """Source en mémoire, construite dans chaque test."""

    nom = "test"

    def __init__(
        self, clients: Iterable[Client], produits: Iterable[Produit], commandes: Iterable[Commande], lots: Iterable[Lot]
    ):
        self.clients = {c.id: c for c in clients}
        self.produits = list(produits)
        self.commandes = sorted(commandes, key=lambda c: c.date)
        self.lots = list(lots)

    def get_clients(self):
        return list(self.clients.values())

    def get_client(self, client_id):
        if client_id not in self.clients:
            raise ClientIntrouvable(client_id)
        return self.clients[client_id]

    def get_order_history(self, client_id=None, depuis=None):
        return [
            c
            for c in self.commandes
            if (client_id is None or c.client_id == client_id) and (depuis is None or c.date >= depuis)
        ]

    def get_products(self):
        return self.produits

    def get_stock(self):
        return self.lots

    def date_du_jour(self):
        return AUJOURD_HUI


def client(id_: str, type_: str = "Restaurant", commercial: str = "Julie") -> Client:
    return Client(
        id=id_,
        nom=f"Client {id_}",
        type=type_,
        ville="Lyon",
        contact="M. Test",
        telephone="04 00 00 00 00",
        commercial=commercial,
    )


def produit(code: str, famille: Famille = Famille.FRAIS, prix: float = 10.0, duree_vie: int = 10) -> Produit:
    return Produit(
        code=code,
        libelle=f"Produit {code}",
        categorie="Crèmerie" if famille is Famille.FRAIS else "Surgelés",
        famille=famille,
        unite="kg",
        prix_unitaire_ht=prix,
        duree_vie_jours=duree_vie,
    )


def commande(id_: str, client_id: str, jours_avant: int, lignes: list[tuple[str, float]]) -> Commande:
    """`lignes` : (code, quantité) au prix de 10 €."""
    return Commande(
        id=id_,
        client_id=client_id,
        date=AUJOURD_HUI - timedelta(days=jours_avant),
        lignes=tuple(LigneCommande(produit_code=c, quantite=q, prix_unitaire_ht=10.0) for c, q in lignes),
    )


def lot(id_: str, code: str, quantite: float, jours_avant_dlc: int) -> Lot:
    return Lot(
        id=id_,
        produit_code=code,
        quantite=quantite,
        dlc=AUJOURD_HUI + timedelta(days=jours_avant_dlc),
        date_reception=AUJOURD_HUI - timedelta(days=2),
        entrepot="Test",
    )


def construire_source_simple() -> SourceMinimale:
    """Un restaurant R1 qui commande chaque vendredi depuis 10 semaines :
    - P1 à chaque commande (dernière il y a 7 jours) ;
    - P2 chaque semaine, mais plus rien depuis 5 semaines (décroché) ;
    - P3 une seule fois (occasionnel).
    Deux autres restaurants (R2, R3) achètent P4, que R1 n'a jamais acheté.
    B1 est une boulangerie sans aucune commande.
    """
    commandes = []
    for semaine in range(1, 11):
        jours = 7 * semaine
        lignes: list[tuple[str, float]] = [("P1", 5)]
        if jours >= 35:
            lignes.append(("P2", 2))
        if semaine == 4:
            lignes.append(("P3", 1))
        commandes.append(commande(f"A{semaine}", "R1", jours, lignes))
    for i, cid in enumerate(("R2", "R3")):
        for semaine in range(1, 5):
            commandes.append(commande(f"{cid}-{semaine}", cid, 7 * semaine + i, [("P4", 3), ("P1", 1)]))

    produits = [
        produit("P1"),
        produit("P2"),
        produit("P3"),
        produit("P4"),
        produit("P5"),  # acheté par personne
        produit("S1", famille=Famille.SURGELE, duree_vie=365),
    ]
    lots = [
        lot("L1", "P1", 20, 1),  # DLC demain : -30 %
        lot("L2", "P1", 10, 8),
        lot("L3", "P5", 50, 1),  # DLC courte mais pertinent pour personne
        lot("L4", "P4", 5, 0),  # expire aujourd'hui : non livrable, ignoré
        lot("L5", "P4", 5, 9),
    ]
    clients = [client("R1"), client("R2", commercial="Karim"), client("R3"), client("B1", "Boulangerie-pâtisserie")]
    return SourceMinimale(clients, produits, commandes, lots)


@pytest.fixture
def source_simple() -> SourceMinimale:
    return construire_source_simple()


@pytest.fixture
def ref_simple(source_simple: SourceMinimale) -> Referentiel:
    return Referentiel.charger(source_simple)


@pytest.fixture(scope="session")
def mock_source() -> MockDataSource:
    return MockDataSource()


@pytest.fixture(scope="session")
def ref_mock(mock_source: MockDataSource) -> Referentiel:
    return Referentiel.charger(mock_source)


@pytest.fixture
def horloge() -> HorlogeFixe:
    return HorlogeFixe(datetime(2026, 10, 23, 10, 30))


MOT_DE_PASSE_TEST = "mot-de-passe-de-test"
SECRET_TEST = "secret-de-session-pour-les-tests-0123456789"


@pytest.fixture(scope="session")
def hachage_test() -> str:
    # scrypt est volontairement lent : un seul hachage pour toute la session de tests.
    return mots_de_passe.hacher(MOT_DE_PASSE_TEST)


@pytest.fixture
def depot_utilisateurs(hachage_test: str) -> DepotUtilisateursMemoire:
    """Un responsable et une télévendeuse (Julie Moreau, présente dans le jeu de données)."""
    depot = DepotUtilisateursMemoire()
    cree_le = datetime(2026, 10, 1)
    depot.creer(
        Utilisateur(identifiant="resp", nom_affiche="Responsable", role=Role.RESPONSABLE, cree_le=cree_le), hachage_test
    )
    depot.creer(
        Utilisateur(identifiant="julie", nom_affiche="Julie Moreau", role=Role.TELEVENDEUR, cree_le=cree_le),
        hachage_test,
    )
    return depot


@pytest.fixture
def application(
    mock_source: MockDataSource, horloge: HorlogeFixe, depot_utilisateurs: DepotUtilisateursMemoire
) -> Application:
    """Application complète sur le mock, journal en mémoire, IA simulée par défaut."""
    return creer_application(
        Config(mode_llm=ModeLLM.SIMULE, securite=ConfigSecurite(secret_session=SECRET_TEST)),
        source=mock_source,
        depot_journal=DepotMemoire(),
        horloge=horloge,
        depot_utilisateurs=depot_utilisateurs,
        depot_evaluations=DepotEvaluationsMemoire(),
    )


def client_connecte(application: Application, identifiant: str) -> TestClient:
    client = TestClient(creer_app(application))
    reponse = client.post("/auth/connexion", json={"identifiant": identifiant, "mot_de_passe": MOT_DE_PASSE_TEST})
    assert reponse.status_code == 200, reponse.text
    return client


@pytest.fixture
def api(application: Application) -> TestClient:
    """Client HTTP connecté en tant que responsable."""
    return client_connecte(application, "resp")


@pytest.fixture
def api_televendeur(application: Application) -> TestClient:
    """Client HTTP connecté en tant que télévendeuse (Julie Moreau)."""
    return client_connecte(application, "julie")


# --------------------------------------------------------------------------- simulateur du datahub

JETON_SIMULATEUR = "jeton-des-tests"


def servir(app: FastAPI) -> Iterator[str]:
    """Sert une application ASGI sur un port libre, dans un fil d'exécution ; renvoie son URL."""
    prise = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    prise.bind(("127.0.0.1", 0))
    port = prise.getsockname()[1]
    serveur = uvicorn.Server(uvicorn.Config(app, log_level="warning"))
    fil = threading.Thread(target=serveur.run, kwargs={"sockets": [prise]}, daemon=True)
    fil.start()
    limite = time.monotonic() + 10
    while not serveur.started:
        assert time.monotonic() < limite, "le serveur de test n'a pas démarré"
        time.sleep(0.01)
    try:
        yield f"http://127.0.0.1:{port}"
    finally:
        serveur.should_exit = True
        fil.join(timeout=10)
        prise.close()


@pytest.fixture(scope="session")
def url_simulateur() -> Iterator[str]:
    """Simulateur du datahub (données du mock, sans anomalie), joignable en HTTP réel."""
    yield from servir(creer_simulateur(jeton=JETON_SIMULATEUR))


@pytest.fixture(scope="session")
def url_simulateur_anomalies() -> Iterator[str]:
    """Simulateur avec des défauts de données injectés."""
    yield from servir(creer_simulateur(jeton=JETON_SIMULATEUR, anomalies=True))
