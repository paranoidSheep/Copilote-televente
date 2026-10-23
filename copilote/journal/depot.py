"""Stockage des comptes-rendus d'appels.

`DepotJournal` est le contrat ; deux implémentations :
- `DepotSQLite` : fichier SQLite local (une base par poste ou par serveur) ;
- `DepotMemoire` : en mémoire, pour les tests et les démonstrations jetables.

Ce journal est la SEULE donnée écrite par le copilote, et il est local : rien
n'est jamais écrit dans l'ERP ni dans le datahub.
"""

from __future__ import annotations

import json
import sqlite3
import threading
from abc import ABC, abstractmethod
from collections.abc import Iterator
from contextlib import contextmanager
from datetime import datetime
from pathlib import Path

from pydantic import TypeAdapter

from .modeles import CompteRendu, LigneCompteRendu, NouveauCompteRendu

_ADAPTATEUR_LIGNES = TypeAdapter(list[LigneCompteRendu])


class DepotJournal(ABC):
    @abstractmethod
    def enregistrer(self, compte_rendu: NouveauCompteRendu, cree_le: datetime) -> CompteRendu:
        """Enregistre un compte-rendu et le renvoie avec son identifiant."""

    @abstractmethod
    def lister(
        self, client_id: str | None = None, depuis: datetime | None = None, limite: int | None = None
    ) -> list[CompteRendu]:
        """Comptes-rendus du plus récent au plus ancien, filtrés si demandé."""

    @abstractmethod
    def obtenir(self, compte_rendu_id: int) -> CompteRendu | None:
        """Un compte-rendu par son identifiant."""


class DepotMemoire(DepotJournal):
    def __init__(self) -> None:
        self._elements: list[CompteRendu] = []
        self._verrou = threading.Lock()

    def enregistrer(self, compte_rendu: NouveauCompteRendu, cree_le: datetime) -> CompteRendu:
        with self._verrou:
            enregistre = CompteRendu(**compte_rendu.model_dump(), id=len(self._elements) + 1, cree_le=cree_le)
            self._elements.append(enregistre)
            return enregistre

    def lister(
        self, client_id: str | None = None, depuis: datetime | None = None, limite: int | None = None
    ) -> list[CompteRendu]:
        resultat = [
            cr
            for cr in sorted(self._elements, key=lambda c: (c.cree_le, c.id), reverse=True)
            if (client_id is None or cr.client_id == client_id) and (depuis is None or cr.cree_le >= depuis)
        ]
        return resultat[:limite] if limite is not None else resultat

    def obtenir(self, compte_rendu_id: int) -> CompteRendu | None:
        return next((cr for cr in self._elements if cr.id == compte_rendu_id), None)


class DepotSQLite(DepotJournal):
    _SCHEMA = """
        CREATE TABLE IF NOT EXISTS comptes_rendus (
            id          INTEGER PRIMARY KEY AUTOINCREMENT,
            client_id   TEXT NOT NULL,
            televendeur TEXT NOT NULL,
            issue       TEXT NOT NULL,
            notes       TEXT NOT NULL DEFAULT '',
            rappel_le   TEXT,
            mode_fiche  TEXT,
            lignes      TEXT NOT NULL,  -- JSON : liste de LigneCompteRendu
            cree_le     TEXT NOT NULL
        );
        CREATE INDEX IF NOT EXISTS idx_cr_client ON comptes_rendus (client_id, cree_le);
        CREATE INDEX IF NOT EXISTS idx_cr_date ON comptes_rendus (cree_le);
    """

    def __init__(self, chemin: Path) -> None:
        self._chemin = chemin
        chemin.parent.mkdir(parents=True, exist_ok=True)
        with self._connexion() as cnx:
            cnx.executescript(self._SCHEMA)

    @contextmanager
    def _connexion(self) -> Iterator[sqlite3.Connection]:
        # Une connexion par opération : simple et sûr avec les threads de FastAPI.
        cnx = sqlite3.connect(self._chemin)
        cnx.row_factory = sqlite3.Row
        try:
            with cnx:  # transaction : commit si succès, rollback sinon
                yield cnx
        finally:
            cnx.close()

    def enregistrer(self, compte_rendu: NouveauCompteRendu, cree_le: datetime) -> CompteRendu:
        lignes = json.dumps([l.model_dump(mode="json") for l in compte_rendu.lignes], ensure_ascii=False)
        with self._connexion() as cnx:
            curseur = cnx.execute(
                "INSERT INTO comptes_rendus (client_id, televendeur, issue, notes, rappel_le, mode_fiche, lignes, cree_le)"
                " VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
                (
                    compte_rendu.client_id,
                    compte_rendu.televendeur,
                    compte_rendu.issue.value,
                    compte_rendu.notes,
                    compte_rendu.rappel_le.isoformat() if compte_rendu.rappel_le else None,
                    compte_rendu.mode_fiche,
                    lignes,
                    cree_le.isoformat(),
                ),
            )
            identifiant = curseur.lastrowid
        assert identifiant is not None
        return CompteRendu(**compte_rendu.model_dump(), id=identifiant, cree_le=cree_le)

    def lister(
        self, client_id: str | None = None, depuis: datetime | None = None, limite: int | None = None
    ) -> list[CompteRendu]:
        conditions: list[str] = []
        parametres: list[str | int] = []
        if client_id is not None:
            conditions.append("client_id = ?")
            parametres.append(client_id)
        if depuis is not None:
            conditions.append("cree_le >= ?")
            parametres.append(depuis.isoformat())
        requete = "SELECT * FROM comptes_rendus"
        if conditions:
            requete += " WHERE " + " AND ".join(conditions)
        requete += " ORDER BY cree_le DESC, id DESC"
        if limite is not None:
            requete += " LIMIT ?"
            parametres.append(limite)
        with self._connexion() as cnx:
            return [self._vers_modele(ligne) for ligne in cnx.execute(requete, parametres)]

    def obtenir(self, compte_rendu_id: int) -> CompteRendu | None:
        with self._connexion() as cnx:
            ligne = cnx.execute("SELECT * FROM comptes_rendus WHERE id = ?", (compte_rendu_id,)).fetchone()
        return self._vers_modele(ligne) if ligne is not None else None

    @staticmethod
    def _vers_modele(ligne: sqlite3.Row) -> CompteRendu:
        return CompteRendu(
            id=ligne["id"],
            client_id=ligne["client_id"],
            televendeur=ligne["televendeur"],
            issue=ligne["issue"],
            notes=ligne["notes"],
            rappel_le=ligne["rappel_le"],
            mode_fiche=ligne["mode_fiche"],
            lignes=_ADAPTATEUR_LIGNES.validate_json(ligne["lignes"]),
            cree_le=datetime.fromisoformat(ligne["cree_le"]),
        )
