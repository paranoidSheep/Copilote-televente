"""Copilote télévente : outils métier, agent IA et fiche d'appel."""

from .agent import generer_fiche, ia_disponible
from .fiche import Fiche

__all__ = ["Fiche", "generer_fiche", "ia_disponible"]
