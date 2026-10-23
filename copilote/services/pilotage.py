"""Vues de pilotage : file d'appels du jour et plan d'écoulement du stock."""

from __future__ import annotations

from datetime import datetime, timedelta

from copilote.analyses import FileAppels, PlanEcoulement, construire_file_appels, construire_plan_ecoulement
from copilote.journal import DepotJournal

from .referentiel import FournisseurReferentiel

JOURS_HISTORIQUE_APPELS = 30  # appels récents pris en compte (rappels, refus, « déjà appelé »)


class ServicePilotage:
    def __init__(self, referentiels: FournisseurReferentiel, journal: DepotJournal) -> None:
        self._referentiels = referentiels
        self._journal = journal

    def file_appels(self, televendeur: str | None = None) -> FileAppels:
        ref = self._referentiels.obtenir()
        depuis = datetime.combine(ref.date_du_jour - timedelta(days=JOURS_HISTORIQUE_APPELS), datetime.min.time())
        return construire_file_appels(ref, self._journal.lister(depuis=depuis), televendeur)

    def plan_ecoulement(self) -> PlanEcoulement:
        return construire_plan_ecoulement(self._referentiels.obtenir())

    def televendeurs(self) -> list[str]:
        return sorted({c.commercial for c in self._referentiels.obtenir().clients.values()})
