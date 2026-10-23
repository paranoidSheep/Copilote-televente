"""Stockage des comptes utilisateurs (SQLite local, ou mémoire pour les tests)."""

from __future__ import annotations

import sqlite3
import threading
from abc import ABC, abstractmethod
from collections.abc import Iterator
from contextlib import contextmanager
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path

from copilote.domaine import ErreurCopilote

from .modeles import Role, Utilisateur


class UtilisateurExistant(ErreurCopilote):
    def __init__(self, identifiant: str) -> None:
        super().__init__(f"L'identifiant « {identifiant} » existe déjà.")


class UtilisateurIntrouvable(ErreurCopilote):
    def __init__(self, identifiant: str) -> None:
        super().__init__(f"Utilisateur inconnu : {identifiant}")


@dataclass(frozen=True)
class CompteStocke:
    """Compte complet, hachage compris : ne quitte jamais la couche « comptes »."""

    utilisateur: Utilisateur
    hachage: str


class DepotUtilisateurs(ABC):
    @abstractmethod
    def creer(self, utilisateur: Utilisateur, hachage: str) -> None: ...

    @abstractmethod
    def obtenir(self, identifiant: str) -> CompteStocke | None: ...

    @abstractmethod
    def lister(self) -> list[Utilisateur]: ...

    @abstractmethod
    def modifier_mot_de_passe(self, identifiant: str, hachage: str) -> None: ...

    @abstractmethod
    def modifier_activite(self, identifiant: str, actif: bool) -> None: ...


class DepotUtilisateursMemoire(DepotUtilisateurs):
    def __init__(self) -> None:
        self._comptes: dict[str, CompteStocke] = {}
        self._verrou = threading.Lock()

    def creer(self, utilisateur: Utilisateur, hachage: str) -> None:
        with self._verrou:
            if utilisateur.identifiant in self._comptes:
                raise UtilisateurExistant(utilisateur.identifiant)
            self._comptes[utilisateur.identifiant] = CompteStocke(utilisateur, hachage)

    def obtenir(self, identifiant: str) -> CompteStocke | None:
        return self._comptes.get(identifiant)

    def lister(self) -> list[Utilisateur]:
        return sorted((c.utilisateur for c in self._comptes.values()), key=lambda u: u.identifiant)

    def modifier_mot_de_passe(self, identifiant: str, hachage: str) -> None:
        with self._verrou:
            compte = self._exiger(identifiant)
            self._comptes[identifiant] = CompteStocke(compte.utilisateur, hachage)

    def modifier_activite(self, identifiant: str, actif: bool) -> None:
        with self._verrou:
            compte = self._exiger(identifiant)
            self._comptes[identifiant] = CompteStocke(
                compte.utilisateur.model_copy(update={"actif": actif}), compte.hachage
            )

    def _exiger(self, identifiant: str) -> CompteStocke:
        if (compte := self._comptes.get(identifiant)) is None:
            raise UtilisateurIntrouvable(identifiant)
        return compte


class DepotUtilisateursSQLite(DepotUtilisateurs):
    _SCHEMA = """
        CREATE TABLE IF NOT EXISTS utilisateurs (
            identifiant TEXT PRIMARY KEY,
            nom_affiche TEXT NOT NULL,
            role        TEXT NOT NULL,
            actif       INTEGER NOT NULL DEFAULT 1,
            hachage     TEXT NOT NULL,
            cree_le     TEXT NOT NULL
        );
    """

    def __init__(self, chemin: Path) -> None:
        self._chemin = chemin
        chemin.parent.mkdir(parents=True, exist_ok=True)
        with self._connexion() as cnx:
            cnx.executescript(self._SCHEMA)

    @contextmanager
    def _connexion(self) -> Iterator[sqlite3.Connection]:
        cnx = sqlite3.connect(self._chemin)
        cnx.row_factory = sqlite3.Row
        try:
            with cnx:
                yield cnx
        finally:
            cnx.close()

    def creer(self, utilisateur: Utilisateur, hachage: str) -> None:
        try:
            with self._connexion() as cnx:
                cnx.execute(
                    "INSERT INTO utilisateurs (identifiant, nom_affiche, role, actif, hachage, cree_le)"
                    " VALUES (?, ?, ?, ?, ?, ?)",
                    (
                        utilisateur.identifiant,
                        utilisateur.nom_affiche,
                        utilisateur.role.value,
                        int(utilisateur.actif),
                        hachage,
                        utilisateur.cree_le.isoformat(),
                    ),
                )
        except sqlite3.IntegrityError as exc:
            raise UtilisateurExistant(utilisateur.identifiant) from exc

    def obtenir(self, identifiant: str) -> CompteStocke | None:
        with self._connexion() as cnx:
            ligne = cnx.execute("SELECT * FROM utilisateurs WHERE identifiant = ?", (identifiant,)).fetchone()
        return CompteStocke(self._vers_modele(ligne), ligne["hachage"]) if ligne else None

    def lister(self) -> list[Utilisateur]:
        with self._connexion() as cnx:
            return [self._vers_modele(l) for l in cnx.execute("SELECT * FROM utilisateurs ORDER BY identifiant")]

    def modifier_mot_de_passe(self, identifiant: str, hachage: str) -> None:
        self._modifier("UPDATE utilisateurs SET hachage = ? WHERE identifiant = ?", (hachage, identifiant), identifiant)

    def modifier_activite(self, identifiant: str, actif: bool) -> None:
        self._modifier(
            "UPDATE utilisateurs SET actif = ? WHERE identifiant = ?", (int(actif), identifiant), identifiant
        )

    def _modifier(self, requete: str, parametres: tuple[str | int, ...], identifiant: str) -> None:
        with self._connexion() as cnx:
            if cnx.execute(requete, parametres).rowcount == 0:
                raise UtilisateurIntrouvable(identifiant)

    @staticmethod
    def _vers_modele(ligne: sqlite3.Row) -> Utilisateur:
        return Utilisateur(
            identifiant=ligne["identifiant"],
            nom_affiche=ligne["nom_affiche"],
            role=Role(ligne["role"]),
            actif=bool(ligne["actif"]),
            cree_le=datetime.fromisoformat(ligne["cree_le"]),
        )
