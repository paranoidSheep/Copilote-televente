"""Banc d'évaluation : rédige les fiches de chaque client avec chaque rédacteur, puis les note.

Deux usages :
- `executer()`, synchrone : la commande `python -m scripts.evaluer` et les tests ;
- `lancer()`, en arrière-plan : l'écran « Qualité IA » du labo suit l'avancement
  avec `suivi()` (une campagne avec Claude peut durer plusieurs minutes).

Les fiches sont produites hors cache : une évaluation ne modifie jamais les
fiches servies aux télévendeurs.
"""

from __future__ import annotations

import hashlib
import json
import logging
import threading
import time
from collections.abc import Callable, Sequence
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime

from copilote.agent import creer_boite_outils, definition_soumission
from copilote.agent.prompts import SYSTEME
from copilote.analyses import Referentiel
from copilote.config import ModeLLM
from copilote.domaine import ErreurCopilote
from copilote.evaluation import (
    Campagne,
    DepotEvaluations,
    EtatEvaluation,
    EvaluationFiche,
    ResumeCampagne,
    SuiviEvaluation,
    evaluer_fiche,
    synthetiser,
)

from .fiches import ServiceFiches
from .journal import ErreurValidation
from .referentiel import FournisseurReferentiel

journal = logging.getLogger("copilote.evaluation")

PARALLELISME = 4  # fiches rédigées en même temps (appels au LLM concurrents)

type Progression = Callable[[int, int], None]


class EvaluationEnCours(ErreurCopilote):
    def __init__(self) -> None:
        super().__init__("Une évaluation est déjà en cours : attendez qu'elle se termine.")


def empreinte_prompt(ref: Referentiel) -> str:
    """Identifie la version du prompt système et des outils (12 caractères hexadécimaux).

    Deux campagnes de même empreinte ont été menées avec les mêmes consignes :
    leurs scores sont directement comparables.
    """
    boite = creer_boite_outils(ref, next(iter(ref.clients)), [])
    contenu = {
        "systeme": SYSTEME,
        "outils": [(d.nom, d.description) for d in boite.definitions()],
        "soumission": definition_soumission().model_dump(),
    }
    return hashlib.sha256(json.dumps(contenu, sort_keys=True, ensure_ascii=False).encode()).hexdigest()[:12]


class ServiceEvaluation:
    def __init__(
        self,
        fiches: ServiceFiches,
        referentiels: FournisseurReferentiel,
        depot: DepotEvaluations,
        *,
        maintenant: Callable[[], datetime] = datetime.now,
        chrono: Callable[[], float] = time.perf_counter,
        parallelisme: int = PARALLELISME,
    ) -> None:
        self._fiches = fiches
        self._referentiels = referentiels
        self._depot = depot
        self._maintenant = maintenant
        self._chrono = chrono
        self._parallelisme = parallelisme
        self._verrou = threading.Lock()
        self._suivi: SuiviEvaluation | None = None
        self._fil: threading.Thread | None = None

    @property
    def redacteurs_disponibles(self) -> list[ModeLLM]:
        return self._fiches.modes_disponibles

    # -- Exécution ------------------------------------------------------------------

    def _valider(self, redacteurs: Sequence[ModeLLM], clients: Sequence[str] | None) -> list[str]:
        indisponibles = [r for r in redacteurs if r not in self.redacteurs_disponibles]
        if not redacteurs or indisponibles:
            disponibles = ", ".join(self.redacteurs_disponibles)
            demandes = ", ".join(indisponibles) or "aucun"
            raise ErreurValidation(f"Rédacteur(s) indisponible(s) : {demandes} (disponibles : {disponibles})")
        ref = self._referentiels.obtenir()
        selection = list(clients) if clients else list(ref.clients)
        for client_id in selection:
            ref.client(client_id)  # lève ClientIntrouvable
        return selection

    def executer(
        self,
        redacteurs: Sequence[ModeLLM],
        clients: Sequence[str] | None = None,
        *,
        progression: Progression | None = None,
        enregistrer: bool = True,
    ) -> Campagne:
        """Évalue chaque client avec chaque rédacteur ; enregistre la campagne dans l'historique."""
        selection = self._valider(redacteurs, clients)
        lancee_le = self._maintenant().replace(microsecond=0)
        debut = self._chrono()
        ref = self._referentiels.obtenir()
        travaux = [(r, c) for r in dict.fromkeys(redacteurs) for c in selection]
        faites = 0
        verrou = threading.Lock()

        def evaluer(travail: tuple[ModeLLM, str]) -> EvaluationFiche:
            nonlocal faites
            redacteur, client_id = travail
            production = self._fiches.produire(client_id, redacteur)
            evaluation = evaluer_fiche(production.fiche, production.contexte, redacteur, production.duree_ms)
            with verrou:
                faites += 1
                if progression:
                    progression(faites, len(travaux))
            return evaluation

        with ThreadPoolExecutor(max_workers=self._parallelisme, thread_name_prefix="evaluation") as executeur:
            evaluations = list(executeur.map(evaluer, travaux))  # même ordre que `travaux`

        campagne = Campagne(
            id=None,
            lancee_le=lancee_le,
            duree_ms=round((self._chrono() - debut) * 1000),
            empreinte_prompt=empreinte_prompt(ref),
            source=self._referentiels.nom_source,
            date_donnees=ref.date_du_jour,
            syntheses=tuple(
                synthetiser(r, [e for e in evaluations if e.redacteur is r]) for r in dict.fromkeys(redacteurs)
            ),
            fiches=tuple(evaluations),
        )
        return self._depot.enregistrer(campagne) if enregistrer else campagne

    # -- Exécution en arrière-plan (interface) --------------------------------------

    def lancer(self, redacteurs: Sequence[ModeLLM], clients: Sequence[str] | None = None) -> SuiviEvaluation:
        """Démarre une campagne en arrière-plan ; une seule à la fois."""
        selection = self._valider(redacteurs, clients)
        with self._verrou:
            if self._suivi is not None and self._suivi.etat is EtatEvaluation.EN_COURS:
                raise EvaluationEnCours()
            self._suivi = SuiviEvaluation(
                etat=EtatEvaluation.EN_COURS,
                redacteurs=tuple(dict.fromkeys(redacteurs)),
                faites=0,
                total=len(selection) * len(set(redacteurs)),
                lancee_le=self._maintenant().replace(microsecond=0),
                campagne_id=None,
                erreur=None,
            )
            suivi = self._suivi
        self._fil = threading.Thread(
            target=self._executer_en_fond, args=(list(redacteurs), selection), name="evaluation", daemon=True
        )
        self._fil.start()
        return suivi

    def _mettre_a_jour(self, **modifications: object) -> None:
        with self._verrou:
            if self._suivi is not None:
                self._suivi = self._suivi.model_copy(update=modifications)

    def _executer_en_fond(self, redacteurs: list[ModeLLM], clients: list[str]) -> None:
        try:
            campagne = self.executer(redacteurs, clients, progression=lambda n, _total: self._mettre_a_jour(faites=n))
            self._mettre_a_jour(etat=EtatEvaluation.TERMINEE, campagne_id=campagne.id)
        except Exception as exc:
            journal.exception("Évaluation interrompue")
            self._mettre_a_jour(etat=EtatEvaluation.ECHOUEE, erreur=str(exc) or type(exc).__name__)

    def attendre(self, delai_secondes: float = 60) -> None:
        """Attend la fin de la campagne en arrière-plan (tests, arrêt propre)."""
        if self._fil is not None:
            self._fil.join(delai_secondes)

    def suivi(self) -> SuiviEvaluation | None:
        with self._verrou:
            return self._suivi

    # -- Historique -----------------------------------------------------------------

    def lister(self, limite: int = 20) -> list[ResumeCampagne]:
        return self._depot.lister(limite)

    def obtenir(self, identifiant: int) -> Campagne:
        return self._depot.obtenir(identifiant)
