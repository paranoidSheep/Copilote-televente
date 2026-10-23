"""Contexte complet d'un client : l'ensemble des analyses utiles à sa fiche d'appel."""

from __future__ import annotations

from collections.abc import Sequence

from copilote.journal import CompteRendu

from .appels import HistoriqueAppels, resumer_appels
from .base import Resultat
from .habitudes import HabitudesClient, analyser_habitudes
from .manquants import ProduitsManquants, analyser_manquants
from .referentiel import Referentiel
from .stock import StockAEcouler, analyser_stock_client
from .suggestions import SuggestionsCroisees, analyser_suggestions


class ContexteClient(Resultat):
    habitudes: HabitudesClient
    manquants: ProduitsManquants
    stock: StockAEcouler
    suggestions: SuggestionsCroisees
    appels: HistoriqueAppels


def construire_contexte(ref: Referentiel, client_id: str, comptes_rendus: Sequence[CompteRendu]) -> ContexteClient:
    return ContexteClient(
        habitudes=analyser_habitudes(ref, client_id),
        manquants=analyser_manquants(ref, client_id),
        stock=analyser_stock_client(ref, client_id),
        suggestions=analyser_suggestions(ref, client_id),
        appels=resumer_appels(comptes_rendus, client_id, ref.date_du_jour, ref.regles),
    )
