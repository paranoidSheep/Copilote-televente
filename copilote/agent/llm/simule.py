"""IA simulée : rejoue des rédactions enregistrées, sans appel réseau.

Chaque « cassette » (un fichier JSON par client dans `cassettes/`) décrit une
conversation complète telle que Claude la mènerait : appels d'outils
successifs, puis soumission de la rédaction. Le fournisseur simulé suit
exactement le même protocole que Claude, ce qui permet de démontrer et de
tester toute la chaîne (boucle d'outils, garde-fous, trace) sans clé d'API.

Les cassettes livrées ont été rédigées par Claude à partir des résultats
réels des outils sur le jeu de données fictif.
"""

from __future__ import annotations

import json
import time
from collections.abc import Callable, Mapping, Sequence
from datetime import date
from pathlib import Path

from pydantic import BaseModel, ConfigDict, JsonValue, ValidationError

from .types import (
    AppelOutil,
    Arret,
    DefinitionOutil,
    ErreurFournisseurLLM,
    MessageUtilisateur,
    ReponseLLM,
    ResultatOutil,
    Usage,
)

DOSSIER_CASSETTES = Path(__file__).resolve().parent / "cassettes"
OUTIL_SOUMISSION = "soumettre_fiche"


class AppelEnregistre(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid", json_schema_serialization_defaults_required=True)
    nom: str
    arguments: dict[str, JsonValue]


class TourEnregistre(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid", json_schema_serialization_defaults_required=True)
    texte: str = ""
    appels: list[AppelEnregistre]


class Cassette(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid", json_schema_serialization_defaults_required=True)
    client_id: str
    date_reference: date
    modele: str
    tours: list[TourEnregistre]
    redaction: dict[str, JsonValue]


def charger_cassette(dossier: Path, client_id: str) -> Cassette:
    chemin = dossier / f"{client_id}.json"
    if not chemin.exists():
        raise ErreurFournisseurLLM(f"aucune rédaction simulée enregistrée pour le client {client_id}")
    try:
        return Cassette.model_validate_json(chemin.read_text(encoding="utf-8"))
    except ValidationError as exc:
        raise ErreurFournisseurLLM(f"cassette invalide pour le client {client_id}") from exc


def _jetons(texte: str) -> int:
    """Estimation grossière (≈ 4 caractères par jeton) pour alimenter la trace."""
    return max(1, len(texte) // 4)


class FournisseurSimule:
    nom = "simule"

    def __init__(
        self,
        dossier: Path = DOSSIER_CASSETTES,
        latence_ms: int = 0,
        dormir: Callable[[float], None] = time.sleep,
    ) -> None:
        self._dossier = dossier
        self._latence_ms = latence_ms
        self._dormir = dormir

    @property
    def modele(self) -> str:
        return "claude-sonnet-5-5 (simulé)"

    def ouvrir_session(
        self, systeme: str, outils: Sequence[DefinitionOutil], metadonnees: Mapping[str, str]
    ) -> SessionSimulee:
        client_id = metadonnees.get("client_id")
        if not client_id:
            raise ErreurFournisseurLLM("IA simulée : client_id manquant dans les métadonnées")
        cassette = charger_cassette(self._dossier, client_id)
        noms = {o.nom for o in outils}
        inconnus = {a.nom for t in cassette.tours for a in t.appels} - noms
        if inconnus or OUTIL_SOUMISSION not in noms:
            raise ErreurFournisseurLLM(f"IA simulée : outils non déclarés {sorted(inconnus)}")
        return SessionSimulee(cassette, systeme, self._latence_ms, self._dormir, self.modele)


class SessionSimulee:
    def __init__(
        self,
        cassette: Cassette,
        systeme: str,
        latence_ms: int,
        dormir: Callable[[float], None],
        modele: str,
    ) -> None:
        self._cassette = cassette
        self._tour = 0
        self._attendus: set[str] = set()
        self._contexte_jetons = _jetons(systeme)
        self._latence_ms = latence_ms
        self._dormir = dormir
        self._modele = modele

    def envoyer(self, message: MessageUtilisateur) -> ReponseLLM:
        self._verifier_message(message)
        self._contexte_jetons += _jetons(message if isinstance(message, str) else "".join(r.contenu for r in message))
        if self._latence_ms:
            self._dormir(self._latence_ms / 1000)

        tours = self._cassette.tours
        if self._tour < len(tours):
            tour = tours[self._tour]
            appels = [
                AppelOutil(id=f"sim_{self._tour}_{i}", nom=a.nom, arguments=a.arguments)
                for i, a in enumerate(tour.appels)
            ]
            textes = [tour.texte] if tour.texte else []
        elif self._tour == len(tours):
            appels = [AppelOutil(id=f"sim_{self._tour}_0", nom=OUTIL_SOUMISSION, arguments=self._cassette.redaction)]
            textes = []
        else:
            return self._reponse(Arret.FIN, ["La fiche a déjà été soumise."], [])

        self._tour += 1
        self._attendus = {a.id for a in appels}
        return self._reponse(Arret.OUTILS, textes, appels)

    def _verifier_message(self, message: MessageUtilisateur) -> None:
        """Comme l'API réelle : chaque appel d'outil doit recevoir son résultat."""
        if isinstance(message, str):
            return
        recus = {r.appel_id for r in message if isinstance(r, ResultatOutil)}
        manquants = self._attendus - recus - {f"sim_{len(self._cassette.tours)}_0"}
        if manquants:
            raise ErreurFournisseurLLM(f"IA simulée : résultats d'outils manquants {sorted(manquants)}")

    def _reponse(self, arret: Arret, textes: list[str], appels: list[AppelOutil]) -> ReponseLLM:
        sortie = _jetons(json.dumps([a.model_dump() for a in appels], ensure_ascii=False) + "".join(textes))
        usage = Usage(jetons_entree=self._contexte_jetons, jetons_sortie=sortie)
        self._contexte_jetons += sortie
        return ReponseLLM(arret=arret, modele=self._modele, textes=textes, appels=appels, usage=usage)
