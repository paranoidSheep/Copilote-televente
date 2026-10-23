"""Suggestions croisées : ce qu'achètent les établissements similaires."""

from __future__ import annotations

from .base import Resultat
from .referentiel import Referentiel
from .stock import nb_clients_similaires_acheteurs, situations_stock


class SuggestionCroisee(Resultat):
    code: str
    libelle: str
    categorie: str
    unite: str
    prix_unitaire_ht: float
    nb_clients_similaires_acheteurs: int
    taux_adoption_pct: int
    en_stock_a_ecouler: bool


class SuggestionsCroisees(Resultat):
    client_id: str
    type_client: str
    nb_clients_similaires: int
    produits: list[SuggestionCroisee]


def analyser_suggestions(ref: Referentiel, client_id: str, limite: int = 5) -> SuggestionsCroisees:
    """Produits jamais achetés par le client mais adoptés par les clients du même type.

    Exemple : « 3 boulangeries sur 4 achètent aussi le pain aux raisins cru ».
    """
    client = ref.client(client_id)
    similaires = ref.clients_similaires(client_id)
    regles = ref.regles
    deja_achetes = set(ref.recurrences(client_id))
    a_ecouler = {s.code for s in situations_stock(ref)}

    suggestions: list[SuggestionCroisee] = []
    if similaires:
        minimum = min(regles.achats_min_adoption, len(similaires))
        for code, produit in ref.produits.items():
            if code in deja_achetes:
                continue
            n = nb_clients_similaires_acheteurs(ref, client_id, code)
            taux = n / len(similaires)
            if n < minimum or taux < regles.taux_adoption_min:
                continue
            suggestions.append(
                SuggestionCroisee(
                    code=code,
                    libelle=produit.libelle,
                    categorie=produit.categorie,
                    unite=produit.unite,
                    prix_unitaire_ht=produit.prix_unitaire_ht,
                    nb_clients_similaires_acheteurs=n,
                    taux_adoption_pct=round(taux * 100),
                    en_stock_a_ecouler=code in a_ecouler,
                )
            )
    suggestions.sort(key=lambda s: (-s.taux_adoption_pct, not s.en_stock_a_ecouler, s.code))
    return SuggestionsCroisees(
        client_id=client_id,
        type_client=client.type,
        nb_clients_similaires=len(similaires),
        produits=suggestions[:limite],
    )
