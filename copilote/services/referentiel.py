"""Fourniture de l'instantané de données, rafraîchi périodiquement."""

from __future__ import annotations

import threading
import time
from collections.abc import Callable

from copilote.analyses import Referentiel, ReglesMetier
from copilote.datahub import DataSource


class FournisseurReferentiel:
    """Charge le `Referentiel` depuis la source et le garde en mémoire `duree_secondes`.

    Toutes les requêtes d'une même période travaillent sur le même instantané :
    les écrans (file d'appels, fiche, stock) restent cohérents entre eux.
    """

    def __init__(
        self,
        source: DataSource,
        regles: ReglesMetier,
        duree_secondes: float,
        horloge: Callable[[], float] = time.monotonic,
    ) -> None:
        self._source = source
        self._regles = regles
        self._duree = duree_secondes
        self._horloge = horloge
        self._verrou = threading.Lock()
        self._courant: tuple[float, Referentiel] | None = None

    @property
    def nom_source(self) -> str:
        return self._source.nom

    def obtenir(self) -> Referentiel:
        with self._verrou:
            maintenant = self._horloge()
            if self._courant is None or maintenant - self._courant[0] >= self._duree:
                self._courant = (maintenant, Referentiel.charger(self._source, self._regles))
            return self._courant[1]

    def invalider(self) -> None:
        with self._verrou:
            self._courant = None
