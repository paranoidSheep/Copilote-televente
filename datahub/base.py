"""Interface d'accès aux données de l'ERP (le « datahub »).

Ce module définit :
- les objets métier manipulés par le copilote (client, produit, commande, lot) ;
- l'interface abstraite `DataSource`, que toute source de données doit implémenter.

Le copilote ne connaît QUE cette interface. Brancher le vrai datahub revient donc
à fournir une nouvelle implémentation de `DataSource` (voir `datahub/http.py`),
sans toucher aux outils métier, à l'agent ni à l'API web.

Règle d'or : l'interface est en LECTURE SEULE. Aucune méthode d'écriture
(création de commande, mise à jour de stock…) n'existe ni ne doit être ajoutée.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from datetime import date
from typing import Literal

from pydantic import BaseModel, Field, computed_field


# ---------------------------------------------------------------------------
# Objets métier
# ---------------------------------------------------------------------------


class Client(BaseModel):
    """Un client professionnel (restaurant, cantine, boulangerie…)."""

    id: str
    nom: str
    type: str = Field(description="Type d'établissement, ex. « Restaurant », « Cantine scolaire »")
    ville: str
    contact: str = Field(description="Nom de l'interlocuteur habituel")
    telephone: str
    commercial: str = Field(description="Télévendeur ou commercial en charge du compte")


class Produit(BaseModel):
    """Un article du catalogue."""

    code: str
    libelle: str
    categorie: str
    famille: Literal["frais", "surgele"]
    unite: str = Field(description="Unité de vente : kg, colis, carton, bac…")
    prix_unitaire_ht: float
    duree_vie_jours: int = Field(description="Durée de vie typique entre réception et DLC")


class LigneCommande(BaseModel):
    produit_code: str
    quantite: float
    prix_unitaire_ht: float


class Commande(BaseModel):
    """Une commande client (historique, déjà facturée ou livrée)."""

    id: str
    client_id: str
    date: date
    lignes: list[LigneCommande]

    @computed_field  # type: ignore[prop-decorator]
    @property
    def montant_ht(self) -> float:
        return round(sum(l.quantite * l.prix_unitaire_ht for l in self.lignes), 2)


class Lot(BaseModel):
    """Un lot physique en stock, avec sa date limite de consommation (DLC)."""

    id: str
    produit_code: str
    quantite: float
    dlc: date
    date_reception: date
    entrepot: str


# ---------------------------------------------------------------------------
# Interface abstraite
# ---------------------------------------------------------------------------


class DataSourceError(RuntimeError):
    """Erreur d'accès à la source de données (configuration, réseau, format…)."""


class ClientIntrouvable(DataSourceError):
    """Le client demandé n'existe pas dans la source."""


class DataSource(ABC):
    """Contrat de lecture des données ERP utilisées par le copilote.

    Toutes les méthodes sont en lecture seule.
    """

    #: Nom court affiché dans l'interface et les logs ("mock", "http"…)
    nom: str = "abstrait"

    @abstractmethod
    def get_clients(self) -> list[Client]:
        """Liste de tous les clients actifs."""

    @abstractmethod
    def get_client(self, client_id: str) -> Client:
        """Un client par son identifiant. Lève `ClientIntrouvable` s'il n'existe pas."""

    @abstractmethod
    def get_order_history(
        self, client_id: str | None = None, depuis: date | None = None
    ) -> list[Commande]:
        """Historique des commandes, triées par date croissante.

        - `client_id` : restreint à un client ; `None` = tous les clients
          (utile pour calculer les rotations de stock et les suggestions croisées).
        - `depuis` : date de début incluse ; `None` = tout l'historique disponible.
        """

    @abstractmethod
    def get_products(self) -> list[Produit]:
        """Catalogue produits."""

    @abstractmethod
    def get_stock(self) -> list[Lot]:
        """Stock disponible, détaillé par lot avec DLC."""

    def date_du_jour(self) -> date:
        """Date de référence des calculs (« aujourd'hui »).

        La source réelle renvoie la date du jour. Le mock la surcharge pour renvoyer
        la date à laquelle le jeu de données a été généré, afin que la démo reste
        cohérente quel que soit le jour où on la lance.
        """
        return date.today()
