"""Interface d'accès aux données de l'ERP (le « datahub »), en LECTURE SEULE.

Le copilote ne connaît que ce contrat. Brancher le vrai datahub revient à
fournir une implémentation de `DataSource` (voir `http.py`) sans toucher au
reste de l'application.

Règle d'or : aucune méthode d'écriture n'existe ni ne doit être ajoutée.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from datetime import date

from copilote.domaine import Client, Commande, Lot, Produit


class DataSource(ABC):
    """Contrat de lecture des données ERP utilisées par le copilote."""

    #: Nom court affiché dans l'interface et les journaux (« mock », « http »…)
    nom: str = "abstrait"

    @abstractmethod
    def get_clients(self) -> list[Client]:
        """Liste de tous les clients actifs."""

    @abstractmethod
    def get_client(self, client_id: str) -> Client:
        """Un client par son identifiant. Lève `ClientIntrouvable` s'il n'existe pas."""

    @abstractmethod
    def get_order_history(self, client_id: str | None = None, depuis: date | None = None) -> list[Commande]:
        """Historique des commandes, trié par date croissante.

        - `client_id` : restreint à un client ; `None` = tous les clients ;
        - `depuis` : date de début incluse ; `None` = tout l'historique disponible.
        """

    @abstractmethod
    def get_products(self) -> list[Produit]:
        """Catalogue produits."""

    @abstractmethod
    def get_stock(self) -> list[Lot]:
        """Stock disponible, détaillé par lot avec DLC."""

    def date_du_jour(self) -> date:
        """Date de référence des calculs.

        La source réelle renvoie la date du jour ; le mock la surcharge avec la
        date de son jeu de données pour que la démo soit reproductible.
        """
        return date.today()
