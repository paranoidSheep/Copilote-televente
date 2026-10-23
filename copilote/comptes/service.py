"""Gestion des comptes et authentification."""

from __future__ import annotations

import logging
import threading
import time
from collections.abc import Callable
from datetime import datetime

from copilote.domaine import ErreurConfiguration, ErreurCopilote

from . import mots_de_passe
from .depot import DepotUtilisateurs, UtilisateurIntrouvable
from .modeles import Role, Utilisateur
from .sessions import SignataireSessions, empreinte_mot_de_passe

journal = logging.getLogger("copilote.comptes")

MAX_ECHECS = 5  # tentatives de connexion ratées avant blocage temporaire
DUREE_BLOCAGE_SECONDES = 60.0


class AuthentificationRefusee(ErreurCopilote):
    """Identifiants incorrects, compte désactivé ou trop de tentatives (message volontairement neutre)."""


class TropDeTentatives(AuthentificationRefusee):
    pass


class _Limiteur:
    """Bloque temporairement un identifiant après plusieurs échecs (attaque par force brute)."""

    def __init__(self, horloge: Callable[[], float]) -> None:
        self._horloge = horloge
        self._echecs: dict[str, list[float]] = {}
        self._verrou = threading.Lock()

    def bloque(self, cle: str) -> bool:
        with self._verrou:
            recents = [t for t in self._echecs.get(cle, []) if self._horloge() - t < DUREE_BLOCAGE_SECONDES]
            self._echecs[cle] = recents
            return len(recents) >= MAX_ECHECS

    def echec(self, cle: str) -> None:
        with self._verrou:
            self._echecs.setdefault(cle, []).append(self._horloge())

    def succes(self, cle: str) -> None:
        with self._verrou:
            self._echecs.pop(cle, None)


class ServiceComptes:
    def __init__(
        self,
        depot: DepotUtilisateurs,
        signataire: SignataireSessions | None = None,  # absent pour l'administration en ligne de commande
        maintenant: Callable[[], datetime] = datetime.now,
        chrono: Callable[[], float] = time.monotonic,
    ) -> None:
        # Les comptes et les sessions suivent l'heure réelle (et non la date figée du jeu de démonstration).
        self._depot = depot
        self._signataire = signataire
        self._maintenant_reel = maintenant
        self._limiteur = _Limiteur(chrono)

    @property
    def signataire(self) -> SignataireSessions:
        if self._signataire is None:
            raise ErreurConfiguration("Sessions indisponibles : aucun signataire configuré.")
        return self._signataire

    @property
    def duree_session_secondes(self) -> int:
        return int(self.signataire.duree.total_seconds())

    # -- Administration ---------------------------------------------------------------

    def creer(self, identifiant: str, nom_affiche: str, role: Role, mot_de_passe: str) -> Utilisateur:
        utilisateur = Utilisateur(
            identifiant=identifiant, nom_affiche=nom_affiche, role=role, cree_le=self._maintenant()
        )
        self._depot.creer(utilisateur, mots_de_passe.hacher(mot_de_passe))
        journal.info("Compte créé : %s (%s)", identifiant, role)
        return utilisateur

    def changer_mot_de_passe(self, identifiant: str, mot_de_passe: str) -> None:
        self._depot.modifier_mot_de_passe(identifiant, mots_de_passe.hacher(mot_de_passe))
        journal.info("Mot de passe modifié : %s (sessions ouvertes invalidées)", identifiant)

    def activer(self, identifiant: str, actif: bool) -> None:
        self._depot.modifier_activite(identifiant, actif)

    def lister(self) -> list[Utilisateur]:
        return self._depot.lister()

    def obtenir(self, identifiant: str) -> Utilisateur:
        compte = self._depot.obtenir(identifiant)
        if compte is None:
            raise UtilisateurIntrouvable(identifiant)
        return compte.utilisateur

    # -- Authentification ---------------------------------------------------------------

    def connecter(self, identifiant: str, mot_de_passe: str) -> tuple[Utilisateur, str]:
        """Vérifie les identifiants et renvoie l'utilisateur avec un jeton de session."""
        cle = identifiant.strip().lower()
        if self._limiteur.bloque(cle):
            journal.warning("Connexion bloquée (trop de tentatives) : %s", cle)
            raise TropDeTentatives("Trop de tentatives : réessayez dans une minute.")
        compte = self._depot.obtenir(cle)
        if compte is None or not mots_de_passe.verifier(mot_de_passe, compte.hachage) or not compte.utilisateur.actif:
            self._limiteur.echec(cle)
            journal.warning("Échec de connexion : %s", cle)
            raise AuthentificationRefusee("Identifiant ou mot de passe incorrect.")
        self._limiteur.succes(cle)
        journal.info("Connexion : %s", cle)
        return compte.utilisateur, self.signataire.emettre(cle, compte.hachage, self._maintenant())

    def utilisateur_de_session(self, jeton: str) -> Utilisateur | None:
        """Utilisateur correspondant à un jeton valide, actif et toujours d'actualité."""
        session = self.signataire.verifier(jeton, self._maintenant())
        if session is None:
            return None
        compte = self._depot.obtenir(session.identifiant)
        if compte is None or not compte.utilisateur.actif:
            return None
        if empreinte_mot_de_passe(compte.hachage) != session.empreinte:
            return None  # mot de passe changé depuis l'ouverture de la session
        return compte.utilisateur

    def _maintenant(self) -> datetime:
        return self._maintenant_reel().replace(microsecond=0)
