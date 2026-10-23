"""Diagnostic des données à la demande (écran « Données » et `python -m copilote.diagnostic`)."""

from __future__ import annotations

import time
from collections.abc import Callable
from datetime import datetime

from copilote.analyses import ReglesMetier
from copilote.datahub import DataSource, sans_cache
from copilote.diagnostic import RapportDiagnostic, diagnostiquer


class ServiceDiagnostic:
    """Interroge directement la source (sans le cache) pour mesurer ses vrais temps de réponse."""

    def __init__(
        self,
        source: DataSource,
        regles: ReglesMetier,
        maintenant: Callable[[], datetime] = datetime.now,
        chrono: Callable[[], float] = time.perf_counter,
    ) -> None:
        self._source = sans_cache(source)
        self._regles = regles
        self._maintenant = maintenant
        self._chrono = chrono

    def executer(self) -> RapportDiagnostic:
        return diagnostiquer(
            self._source, self._regles.periode_analyse_jours, maintenant=self._maintenant, chrono=self._chrono
        )
