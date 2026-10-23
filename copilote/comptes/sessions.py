"""Jetons de session signés (HMAC-SHA256), transportés dans un cookie HttpOnly.

Le jeton contient l'identifiant, l'échéance et une empreinte du hachage du mot
de passe : changer le mot de passe d'un utilisateur invalide aussitôt toutes
ses sessions ouvertes. Aucune donnée de session n'est stockée côté serveur.
"""

from __future__ import annotations

import base64
import hashlib
import hmac
import json
from dataclasses import dataclass
from datetime import datetime, timedelta

from pydantic import BaseModel, ConfigDict, ValidationError


class _Charge(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")
    id: str
    exp: int  # échéance, en secondes depuis l'époque Unix
    emp: str  # empreinte du hachage du mot de passe


@dataclass(frozen=True)
class SessionValide:
    identifiant: str
    empreinte: str
    expire_le: datetime


def _b64(donnees: bytes) -> str:
    return base64.urlsafe_b64encode(donnees).rstrip(b"=").decode()


def _deb64(texte: str) -> bytes:
    return base64.urlsafe_b64decode(texte + "=" * (-len(texte) % 4))


def empreinte_mot_de_passe(hachage: str) -> str:
    return hashlib.sha256(hachage.encode()).hexdigest()[:16]


class SignataireSessions:
    def __init__(self, secret: str, duree: timedelta) -> None:
        if len(secret) < 32:
            raise ValueError("Le secret de session doit contenir au moins 32 caractères.")
        self._cle = secret.encode()
        self.duree = duree

    def _signature(self, contenu: str) -> str:
        return _b64(hmac.new(self._cle, contenu.encode(), hashlib.sha256).digest())

    def emettre(self, identifiant: str, hachage: str, maintenant: datetime) -> str:
        charge = _Charge(
            id=identifiant, exp=int((maintenant + self.duree).timestamp()), emp=empreinte_mot_de_passe(hachage)
        )
        contenu = _b64(charge.model_dump_json().encode())
        return f"{contenu}.{self._signature(contenu)}"

    def verifier(self, jeton: str, maintenant: datetime) -> SessionValide | None:
        """La session si le jeton est authentique et non expiré, sinon `None`."""
        contenu, _, signature = jeton.partition(".")
        if not contenu or not hmac.compare_digest(signature, self._signature(contenu)):
            return None
        try:
            charge = _Charge.model_validate(json.loads(_deb64(contenu)))
        except (ValueError, ValidationError):
            return None
        expire_le = datetime.fromtimestamp(charge.exp)
        if expire_le <= maintenant:
            return None
        return SessionValide(identifiant=charge.id, empreinte=charge.emp, expire_le=expire_le)
