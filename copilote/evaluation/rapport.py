"""Rapport Markdown d'une campagne : lisible dans un terminal, une revue de code ou un courriel."""

from __future__ import annotations

from collections.abc import Iterable

from copilote.config import ModeLLM
from copilote.fiche import TypeCorrection

from .modeles import Campagne, EvaluationFiche, SyntheseRedacteur
from .tarifs import DATE_DES_TARIFS

LIBELLES_REDACTEURS = {ModeLLM.ANTHROPIC: "Claude", ModeLLM.SIMULE: "IA simulée", ModeLLM.REPLI: "Repli (sans IA)"}
LIBELLES_CORRECTIONS = {
    TypeCorrection.PRODUIT_INCONNU: "Produit inventé écarté",
    TypeCorrection.OFFRE_REFUSEE: "Offre refusée récemment retirée",
    TypeCorrection.REMISE_PLAFONNEE: "Remise ramenée au maximum",
    TypeCorrection.SELECTION_LIMITEE: "Sélection trop longue",
    TypeCorrection.STOCK_COMPLETE: "Stock complété par les analyses",
    TypeCorrection.ACCROCHE_RETIREE: "Accroche vantant une offre retirée",
    TypeCorrection.ACCROCHES_LIMITEES: "Accroches trop nombreuses",
    TypeCorrection.ACCROCHES_COMPLETEES: "Accroches complétées",
    TypeCorrection.RAPPEL_AJOUTE: "Rappel promis oublié",
}
SEUIL_DETAIL = 100  # les fiches sous ce score sont détaillées
COLONNES_SYNTHESE = [
    "Rédacteur",
    "Score",
    "Fidélité",
    "Couverture",
    "Format",
    "Sans défaut",
    "Repli",
    "Latence médiane",
    "Coût / fiche",
]


def _nombre(valeur: float) -> str:
    return f"{valeur:.1f}".replace(".", ",")


def _cout(synthese: SyntheseRedacteur) -> str:
    if synthese.cout_par_fiche_usd is None:
        return "—"
    projete = " (projeté)" if synthese.cout_projete else ""
    return f"{synthese.cout_par_fiche_usd:.4f} $".replace(".", ",") + projete


def _tableau(entetes: list[str], lignes: Iterable[list[str]]) -> list[str]:
    return [
        "| " + " | ".join(entetes) + " |",
        "|" + "|".join("---" for _ in entetes) + "|",
        *("| " + " | ".join(ligne) + " |" for ligne in lignes),
    ]


def _problemes(e: EvaluationFiche) -> str:
    morceaux = [LIBELLES_CORRECTIONS[c.type] for c in e.corrections]
    morceaux += list(e.remises_hors_regle)
    morceaux += [f"signal manqué : {s.libelle}" for s in e.signaux if not s.couvert]
    morceaux += [f"{c.libelle} ({c.detail})" for c in e.controles_format if not c.reussi]
    if e.repli_force:
        morceaux.insert(0, "IA en échec, fiche en repli")
    return " ; ".join(morceaux) or "—"


def en_markdown(campagne: Campagne) -> str:
    lignes = [
        f"# Évaluation de la qualité des fiches — {campagne.lancee_le:%d/%m/%Y %H:%M}",
        "",
        f"- Version du prompt : `{campagne.empreinte_prompt}`",
        f"- Données : source « {campagne.source} » au {campagne.date_donnees:%d/%m/%Y}, "
        f"{len({f.client_id for f in campagne.fiches})} clients",
        f"- Durée : {_nombre(campagne.duree_ms / 1000)} s",
        "",
        "## Synthèse par rédacteur",
        "",
        *_tableau(
            COLONNES_SYNTHESE,
            (
                [
                    LIBELLES_REDACTEURS[s.redacteur] + (f" · {s.modele}" if s.modele else ""),
                    f"**{_nombre(s.score_global)}**",
                    _nombre(s.score_fidelite),
                    f"{_nombre(s.score_couverture)} ({s.signaux_couverts}/{s.signaux_total} signaux)",
                    _nombre(s.score_format),
                    f"{s.fiches_sans_defaut}/{s.nb_fiches}",
                    f"{s.taux_repli_pct} %",
                    f"{s.latence_mediane_ms} ms",
                    _cout(s),
                ]
                for s in campagne.syntheses
            ),
        ),
        "",
        f"Coûts estimés aux tarifs publics de l'API Anthropic du {DATE_DES_TARIFS} ; « projeté » : IA simulée, "
        "au tarif du modèle imité.",
    ]
    for synthese in campagne.syntheses:
        if not (synthese.corrections or synthese.defauts_format or synthese.remises_hors_regle):
            continue
        lignes += ["", f"### Défauts — {LIBELLES_REDACTEURS[synthese.redacteur]}", ""]
        lignes += [f"- {LIBELLES_CORRECTIONS[c.type]} : {c.nombre}" for c in synthese.corrections]
        lignes += [f"- {d.libelle} : {d.nombre} fiche(s) en défaut" for d in synthese.defauts_format]
        if synthese.remises_hors_regle:
            lignes.append(f"- Remises annoncées sans être proposées : {synthese.remises_hors_regle}")
    a_detailler = [f for f in campagne.fiches if f.score_global < SEUIL_DETAIL]
    lignes += ["", "## Fiches à revoir", ""]
    if a_detailler:
        lignes += _tableau(
            ["Client", "Rédacteur", "Score", "Points relevés"],
            (
                [f"{f.client_id} {f.client_nom}", LIBELLES_REDACTEURS[f.redacteur], str(f.score_global), _problemes(f)]
                for f in sorted(a_detailler, key=lambda f: (f.score_global, f.client_id))
            ),
        )
    else:
        lignes.append("Aucune : toutes les fiches obtiennent 100.")
    return "\n".join(lignes) + "\n"
