"""Vues de pilotage : file d'appels du jour et plan d'écoulement du stock."""

from __future__ import annotations

from datetime import datetime, timedelta

from copilote.analyses import (
    FileAppels,
    Journee,
    PlanEcoulement,
    avancement_tournee,
    construire_agenda,
    construire_file_appels,
    construire_plan_ecoulement,
    objectifs_du_jour,
)
from copilote.journal import DepotJournal

from .referentiel import FournisseurReferentiel

JOURS_HISTORIQUE_APPELS = 30  # appels récents pris en compte (rappels, refus, « déjà appelé »)
JOURS_HISTORIQUE_AGENDA = 90  # un rappel promis reste à l'agenda tant qu'il n'est pas traité


class ServicePilotage:
    def __init__(self, referentiels: FournisseurReferentiel, journal: DepotJournal) -> None:
        self._referentiels = referentiels
        self._journal = journal

    def file_appels(self, televendeur: str | None = None) -> FileAppels:
        ref = self._referentiels.obtenir()
        depuis = datetime.combine(ref.date_du_jour - timedelta(days=JOURS_HISTORIQUE_APPELS), datetime.min.time())
        return construire_file_appels(ref, self._journal.lister(depuis=depuis), televendeur)

    def journee(self, televendeur: str | None = None) -> Journee:
        """Objectifs du jour, agenda des rappels et avancement de la tournée."""
        ref = self._referentiels.obtenir()
        depuis = datetime.combine(ref.date_du_jour - timedelta(days=JOURS_HISTORIQUE_AGENDA), datetime.min.time())
        comptes_rendus = self._journal.lister(depuis=depuis)
        return Journee(
            date_du_jour=ref.date_du_jour,
            televendeur=televendeur,
            objectifs=objectifs_du_jour(
                comptes_rendus, ref.date_du_jour, ref.regles, televendeur, nb_televendeurs=len(self.televendeurs())
            ),
            agenda=construire_agenda(ref, comptes_rendus, televendeur),
            tournee=avancement_tournee(self.file_appels(televendeur)),
        )

    def plan_ecoulement(self) -> PlanEcoulement:
        return construire_plan_ecoulement(self._referentiels.obtenir())

    def televendeurs(self) -> list[str]:
        # Un client sans télévendeur attribué (champ vide) n'ajoute pas de file « vide ».
        return sorted({c.commercial for c in self._referentiels.obtenir().clients.values() if c.commercial})
