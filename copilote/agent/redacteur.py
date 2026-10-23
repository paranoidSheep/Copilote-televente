"""Boucle de rédaction : le LLM appelle les outils, puis soumet sa rédaction.

Indépendante du fournisseur : fonctionne à l'identique avec Claude et avec
l'IA simulée. Chaque étape est chronométrée et consignée dans la trace.
"""

from __future__ import annotations

import time
from collections.abc import Callable
from dataclasses import dataclass
from datetime import date

from pydantic import ValidationError

from copilote.domaine import Client, ErreurCopilote
from copilote.fiche import EtapeTrace, Redaction, TraceExecution, TypeEtape

from .llm import Arret, FournisseurLLM, MessageUtilisateur, ReponseLLM, ResultatOutil
from .llm.simule import OUTIL_SOUMISSION
from .outils import BoiteAOutils, definition_soumission
from .prompts import RELANCE_SOUMISSION, SYSTEME, demande_fiche

MAX_TOURS = 6  # garde-fou : nombre maximum d'allers-retours avec le LLM
TAILLE_DETAIL = 600  # caractères conservés dans la trace pour chaque entrée/sortie


class ErreurRedaction(ErreurCopilote):
    """La rédaction IA n'a pas abouti ; la trace est conservée pour le diagnostic."""

    def __init__(self, raison: str, trace: TraceExecution) -> None:
        super().__init__(raison)
        self.raison = raison
        self.trace = trace


@dataclass(frozen=True)
class ResultatRedaction:
    redaction: Redaction
    trace: TraceExecution


def _tronquer(texte: str) -> str:
    return texte if len(texte) <= TAILLE_DETAIL else texte[:TAILLE_DETAIL] + "…"


class _Chronometre:
    def __init__(self, horloge: Callable[[], float]) -> None:
        self._horloge = horloge
        self._origine = horloge()

    def ms(self) -> int:
        return round((self._horloge() - self._origine) * 1000)


class RedacteurIA:
    def __init__(
        self, fournisseur: FournisseurLLM, max_tours: int = MAX_TOURS, horloge: Callable[[], float] = time.perf_counter
    ) -> None:
        self._fournisseur = fournisseur
        self._max_tours = max_tours
        self._horloge = horloge

    def rediger(self, client: Client, date_du_jour: date, outils: BoiteAOutils) -> ResultatRedaction:
        chrono = _Chronometre(self._horloge)
        trace = TraceExecution(fournisseur=self._fournisseur.nom, modele=self._fournisseur.modele)

        def echec(raison: str) -> ErreurRedaction:
            trace.duree_totale_ms = chrono.ms()
            return ErreurRedaction(raison, trace)

        try:
            session = self._fournisseur.ouvrir_session(
                SYSTEME, [*outils.definitions(), definition_soumission()], {"client_id": client.id}
            )
            message: MessageUtilisateur = demande_fiche(client, date_du_jour)
            relance_faite = False

            for tour in range(1, self._max_tours + 1):
                debut = chrono.ms()
                reponse = session.envoyer(message)
                trace.etapes.append(self._etape_llm(tour, reponse, debut, chrono.ms() - debut))

                if reponse.arret is Arret.REFUS:
                    raise echec("le modèle a refusé la requête")
                if reponse.arret is Arret.LIMITE:
                    raise echec("réponse tronquée (limite de jetons)")

                soumission = next((a for a in reponse.appels if a.nom == OUTIL_SOUMISSION), None)
                if soumission is not None:
                    try:
                        redaction = Redaction.model_validate(soumission.arguments)
                    except ValidationError as exc:
                        raise echec(f"rédaction mal formée ({exc.error_count()} erreur(s))") from exc
                    trace.duree_totale_ms = chrono.ms()
                    return ResultatRedaction(redaction=redaction, trace=trace)

                if not reponse.appels:
                    if relance_faite:
                        raise echec("le modèle n'a pas soumis de fiche")
                    relance_faite = True
                    message = RELANCE_SOUMISSION
                    continue

                resultats: list[ResultatOutil] = []
                for appel in reponse.appels:
                    debut = chrono.ms()
                    resultat = outils.executer(appel)
                    resultats.append(resultat)
                    trace.etapes.append(
                        EtapeTrace(
                            type=TypeEtape.OUTIL,
                            nom=appel.nom,
                            debut_ms=debut,
                            duree_ms=chrono.ms() - debut,
                            resume=f"{appel.nom}({', '.join(f'{k}={v}' for k, v in appel.arguments.items())})",
                            detail=_tronquer(resultat.contenu),
                            erreur=resultat.est_erreur,
                        )
                    )
                message = resultats  # tous les résultats repartent dans un seul message
        except ErreurRedaction:
            raise
        except ErreurCopilote as exc:  # erreur du fournisseur (réseau, quota, cassette…)
            raise echec(str(exc)) from exc

        raise echec(f"pas de fiche après {self._max_tours} échanges")

    @staticmethod
    def _etape_llm(tour: int, reponse: ReponseLLM, debut: int, duree: int) -> EtapeTrace:
        if reponse.appels:
            resume = f"Tour {tour} : {len(reponse.appels)} appel(s) — " + ", ".join(a.nom for a in reponse.appels)
        else:
            resume = f"Tour {tour} : réponse texte ({reponse.arret})"
        return EtapeTrace(
            type=TypeEtape.APPEL_LLM,
            nom=reponse.modele,
            debut_ms=debut,
            duree_ms=duree,
            resume=resume,
            detail=_tronquer(" ".join(reponse.textes)) or None,
            jetons_entree=reponse.usage.jetons_entree,
            jetons_sortie=reponse.usage.jetons_sortie,
        )
