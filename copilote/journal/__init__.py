"""Journal des appels : comptes-rendus saisis par les télévendeurs (stockage local)."""

from .depot import DepotJournal, DepotMemoire, DepotSQLite
from .modeles import (
    CompteRendu,
    Issue,
    LigneCompteRendu,
    NouveauCompteRendu,
    Origine,
    Reponse,
    SaisieCompteRendu,
)
from .statistiques import StatistiquesAppels, calculer_statistiques

__all__ = [
    "CompteRendu",
    "DepotJournal",
    "DepotMemoire",
    "DepotSQLite",
    "Issue",
    "LigneCompteRendu",
    "NouveauCompteRendu",
    "Origine",
    "Reponse",
    "SaisieCompteRendu",
    "StatistiquesAppels",
    "calculer_statistiques",
]
