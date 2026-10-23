"""Hachage des mots de passe (scrypt, bibliothèque standard).

Format stocké : « scrypt$n$r$p$sel$empreinte » (sel et empreinte en base64).
Aucun mot de passe n'est jamais stocké ni journalisé en clair.
"""

from __future__ import annotations

import base64
import hashlib
import hmac
import secrets

from copilote.domaine import ErreurCopilote

from .modeles import LONGUEUR_MIN_MOT_DE_PASSE

N, R, P, LONGUEUR = 2**14, 8, 1, 32


class MotDePasseInvalide(ErreurCopilote):
    """Mot de passe ne respectant pas la politique."""


def verifier_politique(mot_de_passe: str) -> None:
    if len(mot_de_passe) < LONGUEUR_MIN_MOT_DE_PASSE:
        raise MotDePasseInvalide(f"Le mot de passe doit contenir au moins {LONGUEUR_MIN_MOT_DE_PASSE} caractères.")
    if mot_de_passe.strip() != mot_de_passe or mot_de_passe.lower() == mot_de_passe.upper():
        raise MotDePasseInvalide(
            "Le mot de passe doit contenir des lettres et ne pas commencer ni finir par un espace."
        )


def _deriver(mot_de_passe: str, sel: bytes, n: int, r: int, p: int) -> bytes:
    return hashlib.scrypt(mot_de_passe.encode(), salt=sel, n=n, r=r, p=p, dklen=LONGUEUR)


def hacher(mot_de_passe: str) -> str:
    verifier_politique(mot_de_passe)
    sel = secrets.token_bytes(16)
    empreinte = _deriver(mot_de_passe, sel, N, R, P)
    b64 = base64.b64encode
    return f"scrypt${N}${R}${P}${b64(sel).decode()}${b64(empreinte).decode()}"


def verifier(mot_de_passe: str, hachage: str) -> bool:
    """Comparaison en temps constant ; faux pour tout hachage mal formé."""
    try:
        algo, n, r, p, sel, empreinte = hachage.split("$")
        if algo != "scrypt":
            return False
        calcul = _deriver(mot_de_passe, base64.b64decode(sel), int(n), int(r), int(p))
        return hmac.compare_digest(calcul, base64.b64decode(empreinte))
    except (ValueError, TypeError):
        return False


def generer_mot_de_passe() -> str:
    """Mot de passe aléatoire lisible (pour les comptes de démonstration)."""
    return "-".join(secrets.token_urlsafe(4) for _ in range(3))
