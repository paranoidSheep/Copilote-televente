"""Génération des fiches d'appel : choix du rédacteur, repli automatique, cache."""

from __future__ import annotations

import threading
from collections.abc import Mapping
from datetime import date

from copilote.agent import RedacteurIA, creer_boite_outils
from copilote.agent.llm import FournisseurLLM
from copilote.agent.redacteur import ErreurRedaction
from copilote.analyses import construire_contexte
from copilote.config import ModeLLM
from copilote.fiche import Fiche, ModeFiche, TraceExecution, assembler_fiche, rediger_sans_ia
from copilote.horloge import Horloge
from copilote.journal import DepotJournal

from .referentiel import FournisseurReferentiel

MODE_FICHE: dict[ModeLLM, ModeFiche] = {
    ModeLLM.ANTHROPIC: ModeFiche.IA,
    ModeLLM.SIMULE: ModeFiche.IA_SIMULEE,
    ModeLLM.REPLI: ModeFiche.REPLI,
}


class ServiceFiches:
    def __init__(
        self,
        referentiels: FournisseurReferentiel,
        journal: DepotJournal,
        fournisseurs: Mapping[ModeLLM, FournisseurLLM],
        mode_defaut: ModeLLM,
        horloge: Horloge,
    ) -> None:
        if mode_defaut is ModeLLM.AUTO:
            raise ValueError("Le mode par défaut doit être résolu (pas « auto »)")
        self._referentiels = referentiels
        self._journal = journal
        self._fournisseurs = dict(fournisseurs)
        self.mode_defaut = mode_defaut
        self._horloge = horloge
        self._cache: dict[tuple[str, date, ModeLLM], Fiche] = {}
        self._verrou = threading.Lock()

    @property
    def modes_disponibles(self) -> list[ModeLLM]:
        return [*self._fournisseurs, ModeLLM.REPLI]

    def modele(self, mode: ModeLLM) -> str | None:
        fournisseur = self._fournisseurs.get(mode)
        return fournisseur.modele if fournisseur else None

    def generer(self, client_id: str, mode: ModeLLM | None = None, regenerer: bool = False) -> Fiche:
        """Fiche du jour pour un client ; servie depuis le cache sauf si `regenerer`."""
        mode = mode or self.mode_defaut
        ref = self._referentiels.obtenir()
        ref.client(client_id)  # lève ClientIntrouvable avant tout calcul
        cle = (client_id, ref.date_du_jour, mode)
        if not regenerer:
            with self._verrou:
                if (fiche := self._cache.get(cle)) is not None:
                    return fiche

        comptes_rendus = self._journal.lister(client_id=client_id)
        contexte = construire_contexte(ref, client_id, comptes_rendus)
        maintenant = self._horloge.maintenant()

        def repli(avertissement: str | None, trace: TraceExecution | None = None) -> Fiche:
            return assembler_fiche(
                contexte, rediger_sans_ia(contexte), ModeFiche.REPLI, maintenant,
                avertissement=avertissement, trace=trace,
            )

        fournisseur = self._fournisseurs.get(mode)
        if mode is ModeLLM.REPLI:
            fiche = repli(None)
        elif fournisseur is None:
            fiche = repli(f"IA « {mode} » non configurée : fiche rédigée sans IA.")
        else:
            try:
                resultat = RedacteurIA(fournisseur).rediger(
                    contexte.habitudes.client, ref.date_du_jour, creer_boite_outils(ref, client_id, comptes_rendus)
                )
                fiche = assembler_fiche(
                    contexte, resultat.redaction, MODE_FICHE[mode], maintenant,
                    modele=fournisseur.modele, trace=resultat.trace,
                )
            except ErreurRedaction as exc:
                fiche = repli(f"IA indisponible ({exc.raison}) : fiche rédigée sans IA.", exc.trace)

        with self._verrou:
            self._cache[cle] = fiche
        return fiche

    def invalider(self, client_id: str | None = None) -> None:
        """Oublie les fiches en cache (d'un client, ou toutes)."""
        with self._verrou:
            for cle in [c for c in self._cache if client_id is None or c[0] == client_id]:
                del self._cache[cle]
