"""Horloge de l'application.

Les comptes-rendus d'appels sont horodatés à la « date du jour » de la source
de données : avec le mock (date figée), la démo reste cohérente quel que soit
le jour réel ; avec le vrai datahub, c'est simplement l'heure courante.
"""

from __future__ import annotations

from collections.abc import Callable
from datetime import date, datetime
from typing import Protocol


class Horloge(Protocol):
    def maintenant(self) -> datetime: ...


class HorlogeAlignee:
    """Heure réelle, sur la date de référence fournie."""

    def __init__(self, date_reference: Callable[[], date], heure: Callable[[], datetime] = datetime.now) -> None:
        self._date_reference = date_reference
        self._heure = heure

    def maintenant(self) -> datetime:
        return datetime.combine(self._date_reference(), self._heure().time()).replace(microsecond=0)


class HorlogeFixe:
    """Pour les tests."""

    def __init__(self, instant: datetime) -> None:
        self.instant = instant

    def maintenant(self) -> datetime:
        return self.instant
