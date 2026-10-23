"""Outils exposés à l'IA : les analyses métier, liées à un client et à un instantané.

Chaque outil déclare un modèle d'entrée pydantic (qui fournit le schéma JSON
envoyé au LLM et valide les arguments reçus) et renvoie un résultat typé,
sérialisé en JSON pour le LLM.

Garde-fou : les outils sont verrouillés sur le client de la fiche. Un appel
portant sur un autre client est refusé (minimisation des données).
"""

from __future__ import annotations

from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass
from typing import Protocol

from pydantic import BaseModel, ConfigDict, Field, JsonValue, ValidationError

from copilote.analyses import (
    Referentiel,
    analyser_habitudes,
    analyser_manquants,
    analyser_produit,
    analyser_stock_client,
    analyser_suggestions,
    resumer_appels,
)
from copilote.domaine import ErreurCopilote
from copilote.fiche import Redaction
from copilote.journal import CompteRendu

from .llm import AppelOutil, DefinitionOutil, ResultatOutil
from .llm.simule import OUTIL_SOUMISSION


class EntreeClient(BaseModel):
    model_config = ConfigDict(extra="forbid", json_schema_serialization_defaults_required=True)
    client_id: str = Field(description="Identifiant du client, ex. C001")


class EntreeProduit(EntreeClient):
    code: str = Field(description="Code produit, ex. FR007")


class ErreurOutil(ErreurCopilote):
    """Erreur renvoyée au LLM comme résultat d'outil (il peut se corriger)."""


def schema_autonome(modele: type[BaseModel]) -> dict[str, JsonValue]:
    """Schéma JSON sans références ($defs résolus) ni titres : plus lisible pour le LLM."""
    brut = modele.model_json_schema()
    definitions = brut.pop("$defs", {})

    def resoudre(noeud: JsonValue) -> JsonValue:
        if isinstance(noeud, dict):
            ref = noeud.get("$ref")
            if isinstance(ref, str):
                return resoudre(definitions[ref.rsplit("/", 1)[-1]])
            return {k: resoudre(v) for k, v in noeud.items() if k != "title"}
        if isinstance(noeud, list):
            return [resoudre(v) for v in noeud]
        return noeud

    resultat = resoudre(brut)
    assert isinstance(resultat, dict)
    return resultat


class OutilExecutable(Protocol):
    @property
    def nom(self) -> str: ...

    def definition(self) -> DefinitionOutil: ...

    def executer(self, arguments: Mapping[str, JsonValue]) -> str: ...


@dataclass(frozen=True)
class Outil[E: EntreeClient]:
    nom: str
    description: str
    entree: type[E]
    fonction: Callable[[E], BaseModel]
    client_autorise: str

    def definition(self) -> DefinitionOutil:
        return DefinitionOutil(nom=self.nom, description=self.description, schema_entree=schema_autonome(self.entree))

    def executer(self, arguments: Mapping[str, JsonValue]) -> str:
        try:
            entree = self.entree.model_validate(arguments)
        except ValidationError as exc:
            raise ErreurOutil(f"Arguments invalides : {exc.errors(include_url=False)}") from exc
        if entree.client_id != self.client_autorise:
            raise ErreurOutil(f"Accès limité au client de la fiche ({self.client_autorise}).")
        return self.fonction(entree).model_dump_json()


class BoiteAOutils:
    """Ensemble des outils disponibles pour une rédaction."""

    def __init__(self, outils: Sequence[OutilExecutable]) -> None:
        self._outils = {o.nom: o for o in outils}

    @property
    def noms(self) -> list[str]:
        return list(self._outils)

    def definitions(self) -> list[DefinitionOutil]:
        return [o.definition() for o in self._outils.values()]

    def executer(self, appel: AppelOutil) -> ResultatOutil:
        """Exécute un appel ; toute erreur est renvoyée au LLM au lieu d'interrompre la rédaction."""
        outil = self._outils.get(appel.nom)
        if outil is None:
            return ResultatOutil(appel_id=appel.id, contenu=f"Erreur : outil inconnu « {appel.nom} »", est_erreur=True)
        try:
            return ResultatOutil(appel_id=appel.id, contenu=outil.executer(appel.arguments))
        except ErreurCopilote as exc:
            return ResultatOutil(appel_id=appel.id, contenu=f"Erreur : {exc}", est_erreur=True)


def definition_soumission() -> DefinitionOutil:
    return DefinitionOutil(
        nom=OUTIL_SOUMISSION,
        description="Soumet la rédaction finale de la fiche d'appel. À appeler une seule fois, en dernier.",
        schema_entree=schema_autonome(Redaction),
    )


def creer_boite_outils(ref: Referentiel, client_id: str, comptes_rendus: Sequence[CompteRendu]) -> BoiteAOutils:
    """Outils de données, verrouillés sur `client_id` et sur l'instantané `ref`."""
    ref.client(client_id)  # lève ClientIntrouvable

    def outil_client(nom: str, description: str, fonction: Callable[[EntreeClient], BaseModel]) -> Outil[EntreeClient]:
        return Outil(nom, description, EntreeClient, fonction, client_id)

    return BoiteAOutils(
        [
            outil_client(
                "historique_client",
                "Habitudes d'achat du client sur 6 mois : fiche client, nombre de commandes, fréquence, jours "
                "habituels, panier moyen HT, tendance du chiffre d'affaires, catégories et produits récurrents.",
                lambda e: analyser_habitudes(ref, e.client_id),
            ),
            outil_client(
                "produits_habituels_manquants",
                "Produits habituels non commandés depuis plus longtemps que leur rythme habituel. "
                "Statut « decroche » = probable achat chez un concurrent.",
                lambda e: analyser_manquants(ref, e.client_id),
            ),
            outil_client(
                "stock_a_ecouler",
                "Produits à écouler (DLC courte ou surstock) pertinents pour ce client : lot prioritaire, DLC, "
                "remise suggérée (un maximum à ne pas dépasser) et raison de la pertinence.",
                lambda e: analyser_stock_client(ref, e.client_id),
            ),
            outil_client(
                "suggestions_croisees",
                "Produits jamais achetés par ce client mais adoptés par au moins la moitié des clients du même type.",
                lambda e: analyser_suggestions(ref, e.client_id),
            ),
            outil_client(
                "historique_appels",
                "Derniers appels de télévente à ce client : issue, notes, produits acceptés ou refusés, "
                "rappel demandé. Les produits refusés récemment ne doivent pas être reproposés.",
                lambda e: resumer_appels(comptes_rendus, e.client_id, ref.date_du_jour, ref.regles),
            ),
            Outil(
                "details_produit",
                "Détail d'un produit pour ce client : ses achats passés, sa quantité habituelle, les lots en stock "
                "avec DLC, la pertinence et l'adoption par les clients similaires. Pour approfondir un produit.",
                EntreeProduit,
                lambda e: analyser_produit(ref, e.client_id, e.code),
                client_id,
            ),
        ]
    )
