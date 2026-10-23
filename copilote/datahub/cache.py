"""Cache en mémoire devant une source de données lente (le vrai datahub).

`SourceEnCache` enveloppe n'importe quelle `DataSource` et mémorise ses réponses
pendant une durée donnée. Le copilote charge souvent les mêmes données
(catalogue, stock, historique global) : le cache évite de solliciter le datahub
à chaque fiche.
"""

from __future__ import annotations

import threading
import time
from collections.abc import Callable
from datetime import date

from copilote.domaine import Client, Commande, Lot, Produit

from .base import DataSource


class SourceEnCache(DataSource):
    def __init__(
        self, source: DataSource, duree_secondes: float, horloge: Callable[[], float] = time.monotonic
    ) -> None:
        self._source = source
        self._duree = duree_secondes
        self._horloge = horloge
        self._valeurs: dict[tuple[object, ...], tuple[float, object]] = {}
        self._verrou = threading.Lock()
        self.nom = source.nom

    def _memoriser[T](self, cle: tuple[object, ...], calcul: Callable[[], T]) -> T:
        maintenant = self._horloge()
        with self._verrou:
            if (entree := self._valeurs.get(cle)) is not None and maintenant - entree[0] < self._duree:
                return entree[1]  # type: ignore[return-value]
        valeur = calcul()
        with self._verrou:
            self._valeurs[cle] = (maintenant, valeur)
        return valeur

    @property
    def source(self) -> DataSource:
        """La source enveloppée (pour mesurer ses vrais temps de réponse, sans le cache)."""
        return self._source

    def vider(self) -> None:
        with self._verrou:
            self._valeurs.clear()

    def get_clients(self) -> list[Client]:
        return self._memoriser(("clients",), self._source.get_clients)

    def get_client(self, client_id: str) -> Client:
        return self._memoriser(("client", client_id), lambda: self._source.get_client(client_id))

    def get_order_history(self, client_id: str | None = None, depuis: date | None = None) -> list[Commande]:
        return self._memoriser(
            ("commandes", client_id, depuis), lambda: self._source.get_order_history(client_id, depuis)
        )

    def get_products(self) -> list[Produit]:
        return self._memoriser(("produits",), self._source.get_products)

    def get_stock(self) -> list[Lot]:
        return self._memoriser(("stock",), self._source.get_stock)

    def date_du_jour(self) -> date:
        return self._source.date_du_jour()
