"""Génération des fiches d'appel : choix du rédacteur, repli automatique, cache."""

from __future__ import annotations

import threading
import time
from collections.abc import Callable, Mapping
from dataclasses import dataclass
from datetime import date, datetime, timedelta

from copilote.agent import RedacteurIA, creer_boite_outils
from copilote.agent.llm import FournisseurLLM
from copilote.agent.redacteur import ErreurRedaction
from copilote.analyses import ContexteClient, ModeleAcceptation, apprendre, construire_contexte
from copilote.config import ModeLLM
from copilote.fiche import Fiche, ModeFiche, TraceExecution, assembler_fiche, rediger_sans_ia
from copilote.horloge import Horloge
from copilote.journal import DepotJournal

from .referentiel import FournisseurReferentiel


def mode_fiche(mode: ModeLLM) -> ModeFiche:
    """Nature de la fiche : rédigée par une IA (quel que soit le fournisseur), simulée, ou par gabarits."""
    return {ModeLLM.SIMULE: ModeFiche.IA_SIMULEE, ModeLLM.REPLI: ModeFiche.REPLI}.get(mode, ModeFiche.IA)


@dataclass(frozen=True, slots=True)
class Production:
    """Une fiche rédigée, avec le contexte d'analyse dont elle est issue."""

    fiche: Fiche
    contexte: ContexteClient
    duree_ms: int  # analyses + rédaction


class ServiceFiches:
    def __init__(
        self,
        referentiels: FournisseurReferentiel,
        journal: DepotJournal,
        fournisseurs: Mapping[ModeLLM, FournisseurLLM],
        mode_defaut: ModeLLM,
        horloge: Horloge,
        *,
        chrono: Callable[[], float] = time.perf_counter,
    ) -> None:
        if mode_defaut is ModeLLM.AUTO:
            raise ValueError("Le mode par défaut doit être résolu (pas « auto »)")
        self._referentiels = referentiels
        self._journal = journal
        self._fournisseurs = dict(fournisseurs)
        self.mode_defaut = mode_defaut
        self._horloge = horloge
        self._chrono = chrono
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
        fiche = self.produire(client_id, mode).fiche
        with self._verrou:
            self._cache[cle] = fiche
        return fiche

    def apprentissage(self) -> ModeleAcceptation:
        """Taux d'acceptation des offres, appris sur les comptes-rendus de tous les télévendeurs."""
        ref = self._referentiels.obtenir()
        depuis = datetime.combine(
            ref.date_du_jour - timedelta(days=ref.regles.apprentissage_fenetre_jours), datetime.min.time()
        )
        return apprendre(self._journal.lister(depuis=depuis), ref.clients, ref.date_du_jour, ref.regles)

    def produire(self, client_id: str, mode: ModeLLM | None = None) -> Production:
        """Rédige une fiche sans passer par le cache (banc d'évaluation, comparaison des rédacteurs).

        Renvoie aussi le contexte d'analyse utilisé et la durée totale, pour évaluer la fiche.
        """
        debut = self._chrono()
        mode = mode or self.mode_defaut
        ref = self._referentiels.obtenir()
        comptes_rendus = self._journal.lister(client_id=client_id)
        acceptation = self.apprentissage()
        contexte = construire_contexte(ref, client_id, comptes_rendus, acceptation)
        maintenant = self._horloge.maintenant()

        def repli(avertissement: str | None, trace: TraceExecution | None = None) -> Fiche:
            return assembler_fiche(
                contexte,
                rediger_sans_ia(contexte),
                mode=ModeFiche.REPLI,
                genere_le=maintenant,
                avertissement=avertissement,
                trace=trace,
            )

        fournisseur = self._fournisseurs.get(mode)
        if mode is ModeLLM.REPLI:
            fiche = repli(None)
        elif fournisseur is None:
            fiche = repli(f"IA « {mode} » non configurée : fiche rédigée sans IA.")
        else:
            try:
                resultat = RedacteurIA(fournisseur).rediger(
                    contexte.habitudes.client,
                    ref.date_du_jour,
                    creer_boite_outils(ref, client_id, comptes_rendus, acceptation),
                )
                fiche = assembler_fiche(
                    contexte,
                    resultat.redaction,
                    mode=mode_fiche(mode),
                    genere_le=maintenant,
                    modele=fournisseur.modele,
                    trace=resultat.trace,
                )
            except ErreurRedaction as exc:
                fiche = repli(f"IA indisponible ({exc.raison}) : fiche rédigée sans IA.", exc.trace)
        return Production(fiche=fiche, contexte=contexte, duree_ms=round((self._chrono() - debut) * 1000))

    def invalider(self, client_id: str | None = None) -> None:
        """Oublie les fiches en cache (d'un client, ou toutes)."""
        with self._verrou:
            for cle in [c for c in self._cache if client_id is None or c[0] == client_id]:
                del self._cache[cle]
