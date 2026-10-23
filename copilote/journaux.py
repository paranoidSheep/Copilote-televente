"""Configuration des journaux : texte lisible en développement, JSON structuré en production.

En JSON, chaque ligne est un objet (horodatage, niveau, module, message et champs
contextuels comme l'utilisateur, la route ou la durée), directement exploitable
par `jq`, Loki, Elastic ou tout autre outil de supervision.
"""

from __future__ import annotations

import json
import logging
from datetime import UTC, datetime
from typing import Final

CHAMPS_CONTEXTE: Final = ("utilisateur", "methode", "chemin", "statut", "duree_ms", "client_id")


class FormatJSON(logging.Formatter):
    def format(self, enregistrement: logging.LogRecord) -> str:
        donnees: dict[str, object] = {
            "horodatage": datetime.fromtimestamp(enregistrement.created, UTC).isoformat(timespec="milliseconds"),
            "niveau": enregistrement.levelname,
            "module": enregistrement.name,
            "message": enregistrement.getMessage(),
        }
        for champ in CHAMPS_CONTEXTE:
            if hasattr(enregistrement, champ):
                donnees[champ] = getattr(enregistrement, champ)
        if enregistrement.exc_info:
            donnees["exception"] = self.formatException(enregistrement.exc_info)
        return json.dumps(donnees, ensure_ascii=False)


def configurer_journaux(format_journaux: str = "texte", niveau: int = logging.INFO) -> None:
    gestionnaire = logging.StreamHandler()
    if format_journaux == "json":
        gestionnaire.setFormatter(FormatJSON())
    else:
        gestionnaire.setFormatter(logging.Formatter("%(asctime)s %(levelname)s %(name)s : %(message)s"))
    racine = logging.getLogger()
    racine.handlers[:] = [gestionnaire]
    racine.setLevel(niveau)
    # Les accès sont journalisés par le copilote (avec l'utilisateur) : inutile de doubler ceux d'uvicorn.
    logging.getLogger("uvicorn.access").disabled = True
