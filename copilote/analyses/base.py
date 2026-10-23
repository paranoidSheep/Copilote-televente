"""Socle commun aux résultats d'analyse et à leur mémorisation."""

from __future__ import annotations

import threading
import weakref
from collections.abc import Callable
from functools import wraps
from typing import TYPE_CHECKING

from pydantic import BaseModel, ConfigDict

if TYPE_CHECKING:
    from .referentiel import Referentiel


class Resultat(BaseModel):
    """Base des résultats d'analyse : immuables, champs inconnus refusés, sérialisables en JSON."""

    model_config = ConfigDict(frozen=True, extra="forbid", json_schema_serialization_defaults_required=True)


def memoise_par_referentiel[T](calcul: Callable[[Referentiel], T]) -> Callable[[Referentiel], T]:
    """Mémorise le résultat d'un calcul global pour un instantané donné.

    Le cache est lié à la durée de vie du `Referentiel` (référence faible) :
    un nouvel instantané repart d'un cache vide.
    """
    cache: weakref.WeakKeyDictionary[Referentiel, T] = weakref.WeakKeyDictionary()
    verrou = threading.Lock()

    @wraps(calcul)
    def enveloppe(ref: Referentiel) -> T:
        with verrou:
            if ref in cache:
                return cache[ref]
        valeur = calcul(ref)
        with verrou:
            cache[ref] = valeur
        return valeur

    return enveloppe
