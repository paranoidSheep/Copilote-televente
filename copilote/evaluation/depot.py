"""Historique des campagnes d'évaluation (SQLite local, ou mémoire pour les tests).

Chaque campagne est conservée en entier (JSON) : on peut comparer les scores
d'une version du prompt à l'autre, et revoir le détail de n'importe quelle fiche.
"""

from __future__ import annotations

import sqlite3
import threading
from abc import ABC, abstractmethod
from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path

from copilote.domaine import ErreurCopilote

from .modeles import Campagne, ResumeCampagne


class CampagneIntrouvable(ErreurCopilote):
    def __init__(self, identifiant: int) -> None:
        super().__init__(f"Campagne d'évaluation inconnue : {identifiant}")


def resumer(campagne: Campagne) -> ResumeCampagne:
    if campagne.id is None:
        raise ValueError("campagne non enregistrée")
    return ResumeCampagne(
        id=campagne.id,
        lancee_le=campagne.lancee_le,
        duree_ms=campagne.duree_ms,
        empreinte_prompt=campagne.empreinte_prompt,
        source=campagne.source,
        date_donnees=campagne.date_donnees,
        nb_clients=len({f.client_id for f in campagne.fiches}),
        syntheses=campagne.syntheses,
    )


class DepotEvaluations(ABC):
    @abstractmethod
    def enregistrer(self, campagne: Campagne) -> Campagne:
        """Enregistre la campagne et la renvoie avec son identifiant."""

    @abstractmethod
    def obtenir(self, identifiant: int) -> Campagne: ...

    @abstractmethod
    def lister(self, limite: int = 20) -> list[ResumeCampagne]:
        """Les campagnes les plus récentes d'abord."""


class DepotEvaluationsMemoire(DepotEvaluations):
    def __init__(self) -> None:
        self._campagnes: list[Campagne] = []
        self._verrou = threading.Lock()

    def enregistrer(self, campagne: Campagne) -> Campagne:
        with self._verrou:
            enregistree = campagne.model_copy(update={"id": len(self._campagnes) + 1})
            self._campagnes.append(enregistree)
            return enregistree

    def obtenir(self, identifiant: int) -> Campagne:
        with self._verrou:
            if not 1 <= identifiant <= len(self._campagnes):
                raise CampagneIntrouvable(identifiant)
            return self._campagnes[identifiant - 1]

    def lister(self, limite: int = 20) -> list[ResumeCampagne]:
        with self._verrou:
            return [resumer(c) for c in reversed(self._campagnes[-limite:])]


class DepotEvaluationsSQLite(DepotEvaluations):
    _SCHEMA = """
        CREATE TABLE IF NOT EXISTS campagnes (
            id               INTEGER PRIMARY KEY AUTOINCREMENT,
            lancee_le        TEXT NOT NULL,
            empreinte_prompt TEXT NOT NULL,
            contenu          TEXT NOT NULL
        );
    """

    def __init__(self, chemin: Path) -> None:
        # Base créée à la première écriture : lancer l'application ne crée aucun fichier inutile.
        self._chemin = chemin
        self._initialisee = False
        self._verrou = threading.Lock()

    @contextmanager
    def _connexion(self) -> Iterator[sqlite3.Connection]:
        with self._verrou:
            if not self._initialisee:
                self._chemin.parent.mkdir(parents=True, exist_ok=True)
        cnx = sqlite3.connect(self._chemin)
        try:
            with cnx:
                if not self._initialisee:
                    cnx.executescript(self._SCHEMA)
                    self._initialisee = True
                yield cnx
        finally:
            cnx.close()

    def enregistrer(self, campagne: Campagne) -> Campagne:
        with self._connexion() as cnx:
            curseur = cnx.execute(
                "INSERT INTO campagnes (lancee_le, empreinte_prompt, contenu) VALUES (?, ?, '')",
                (campagne.lancee_le.isoformat(), campagne.empreinte_prompt),
            )
            if curseur.lastrowid is None:  # pragma: no cover - toujours renseigné après un INSERT
                raise RuntimeError("identifiant de campagne non attribué")
            enregistree = campagne.model_copy(update={"id": curseur.lastrowid})
            contenu = enregistree.model_dump_json()
            cnx.execute("UPDATE campagnes SET contenu = ? WHERE id = ?", (contenu, enregistree.id))
        return enregistree

    def obtenir(self, identifiant: int) -> Campagne:
        if not self._chemin.exists():
            raise CampagneIntrouvable(identifiant)
        with self._connexion() as cnx:
            ligne = cnx.execute("SELECT contenu FROM campagnes WHERE id = ?", (identifiant,)).fetchone()
        if ligne is None:
            raise CampagneIntrouvable(identifiant)
        return Campagne.model_validate_json(ligne[0])

    def lister(self, limite: int = 20) -> list[ResumeCampagne]:
        if not self._chemin.exists():
            return []
        with self._connexion() as cnx:
            lignes = cnx.execute("SELECT contenu FROM campagnes ORDER BY id DESC LIMIT ?", (limite,)).fetchall()
        return [resumer(Campagne.model_validate_json(contenu)) for (contenu,) in lignes]
