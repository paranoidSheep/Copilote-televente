"""Analyses métier : calculs purs et déterministes sur un `Referentiel`.

Aucune fonction de ce paquet ne fait d'accès réseau ni d'écriture : elles
prennent un instantané des données et renvoient des résultats typés.
"""

from .appels import AppelPrecedent, HistoriqueAppels, resumer_appels
from .base import Resultat
from .contexte import ContexteClient, construire_contexte
from .ecoulement import ClientCible, LigneEcoulement, PlanEcoulement, construire_plan_ecoulement
from .exploitabilite import DonneesExploitables, Ecart, MotifEcart, filtrer_exploitables
from .habitudes import CaMensuel, HabitudesClient, PartCategorie, ProduitRecurrent, analyser_habitudes
from .manquants import ProduitManquant, ProduitsManquants, StatutManquant, analyser_manquants
from .priorisation import FileAppels, NiveauPriorite, PrioriteAppel, RaisonPriorite, construire_file_appels
from .produit import DetailsProduit, analyser_produit
from .referentiel import Referentiel
from .regles import REGLES_PAR_DEFAUT, PoidsPriorite, ReglesMetier
from .statistiques import JourSemaine
from .stock import (
    MotifEcoulement,
    Pertinence,
    PropositionStock,
    SituationStock,
    StockAEcouler,
    analyser_stock_client,
    remise_suggeree,
    seuil_dlc_courte,
    situations_stock,
)
from .suggestions import SuggestionCroisee, SuggestionsCroisees, analyser_suggestions

__all__ = [
    "REGLES_PAR_DEFAUT",
    "AppelPrecedent",
    "CaMensuel",
    "ClientCible",
    "ContexteClient",
    "DetailsProduit",
    "DonneesExploitables",
    "Ecart",
    "FileAppels",
    "HabitudesClient",
    "HistoriqueAppels",
    "JourSemaine",
    "LigneEcoulement",
    "MotifEcart",
    "MotifEcoulement",
    "NiveauPriorite",
    "PartCategorie",
    "Pertinence",
    "PlanEcoulement",
    "PoidsPriorite",
    "PrioriteAppel",
    "ProduitManquant",
    "ProduitRecurrent",
    "ProduitsManquants",
    "PropositionStock",
    "RaisonPriorite",
    "Referentiel",
    "ReglesMetier",
    "Resultat",
    "SituationStock",
    "StatutManquant",
    "StockAEcouler",
    "SuggestionCroisee",
    "SuggestionsCroisees",
    "analyser_habitudes",
    "analyser_manquants",
    "analyser_produit",
    "analyser_stock_client",
    "analyser_suggestions",
    "construire_contexte",
    "construire_file_appels",
    "construire_plan_ecoulement",
    "filtrer_exploitables",
    "remise_suggeree",
    "resumer_appels",
    "seuil_dlc_courte",
    "situations_stock",
]
