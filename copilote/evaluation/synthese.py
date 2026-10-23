"""Synthèse par rédacteur : moyennes, totaux et répartition des défauts."""

from __future__ import annotations

import math
from collections import Counter
from collections.abc import Sequence
from statistics import mean, median

from copilote.config import ModeLLM

from .modeles import CompteCorrection, CompteDefaut, EvaluationFiche, SyntheseRedacteur


def percentile(valeurs: Sequence[int], rang: float) -> int:
    """Percentile « au plus proche rang » (ex. 0,95 : 95 % des valeurs sont inférieures ou égales)."""
    if not valeurs:
        return 0
    ordonnees = sorted(valeurs)
    return ordonnees[max(0, math.ceil(rang * len(ordonnees)) - 1)]


def synthetiser(redacteur: ModeLLM, evaluations: Sequence[EvaluationFiche]) -> SyntheseRedacteur:
    if not evaluations:
        raise ValueError("aucune fiche à synthétiser")
    corrections = Counter(c.type for e in evaluations for c in e.corrections)
    defauts = Counter(c.libelle for e in evaluations for c in e.controles_format if not c.reussi)
    couts = [e.cout_usd for e in evaluations if e.cout_usd is not None]
    durees = [e.duree_ms for e in evaluations]
    modele = next((e.modele for e in evaluations if e.modele), None)
    return SyntheseRedacteur(
        redacteur=redacteur,
        modele=modele,
        nb_fiches=len(evaluations),
        score_global=round(mean(e.score_global for e in evaluations), 1),
        score_fidelite=round(mean(e.score_fidelite for e in evaluations), 1),
        score_couverture=round(mean(e.score_couverture for e in evaluations), 1),
        score_format=round(mean(e.score_format for e in evaluations), 1),
        fiches_sans_defaut=sum(e.score_global == 100 for e in evaluations),
        taux_repli_pct=round(100 * sum(e.repli_force for e in evaluations) / len(evaluations)),
        corrections=tuple(CompteCorrection(type=t, nombre=n) for t, n in corrections.most_common()),
        remises_hors_regle=sum(len(e.remises_hors_regle) for e in evaluations),
        signaux_couverts=sum(s.couvert for e in evaluations for s in e.signaux),
        signaux_total=sum(len(e.signaux) for e in evaluations),
        defauts_format=tuple(CompteDefaut(libelle=l, nombre=n) for l, n in defauts.most_common()),
        latence_mediane_ms=round(median(durees)),
        latence_p95_ms=percentile(durees, 0.95),
        jetons_entree_moyens=round(mean(e.jetons_entree for e in evaluations)),
        jetons_sortie_moyens=round(mean(e.jetons_sortie for e in evaluations)),
        cout_total_usd=round(sum(couts), 4) if couts else None,
        cout_par_fiche_usd=round(sum(couts) / len(couts), 5) if couts else None,
        cout_projete=redacteur is ModeLLM.SIMULE and bool(couts),
    )
