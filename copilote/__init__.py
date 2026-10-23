"""Copilote télévente.

Organisation en couches (chaque couche ne dépend que des couches au-dessus d'elle) :

    domaine    objets métier et erreurs, sans aucune dépendance
    datahub    accès aux données ERP en lecture seule (mock, http, cache)
    analyses   calculs métier purs et déterministes sur un instantané des données
    journal    comptes-rendus d'appels, stockés localement (jamais dans l'ERP)
    fiche      fiche d'appel : modèle, garde-fous d'assemblage, mode repli, rendus
    agent      orchestration IA : fournisseurs LLM, outils, boucle, trace
    api        exposition HTTP (FastAPI) et interface web
"""

__version__ = "0.2.0"
