"""Banc d'évaluation de la qualité des fiches, en ligne de commande.

    python -m scripts.evaluer                              # tous les rédacteurs disponibles, tous les clients
    python -m scripts.evaluer --redacteurs simule,repli --clients C001,C005
    python -m scripts.evaluer --isole --score-minimum 85   # contrôle de non-régression (CI) : code 1 sous 85
    ANTHROPIC_API_KEY=… python -m scripts.evaluer --redacteurs anthropic
    python -m scripts.evaluer --redacteurs anthropic,mistral,compatible   # comparer les fournisseurs configurés

Écrit un rapport JSON (complet) et un rapport Markdown (lisible) dans --sortie,
et enregistre la campagne dans l'historique, consultable dans l'écran « Qualité IA »
du labo (sauf --sans-historique). Avec une vraie IA, chaque fiche est facturée par
le fournisseur : le coût estimé est indiqué dans le rapport (prix connus pour Claude,
à renseigner pour les autres : {PREFIXE}_PRIX_ENTREE et {PREFIXE}_PRIX_SORTIE).

Les fiches tiennent compte de l'historique d'appels du journal (refus, rappels) : les
scores dépendent donc de son contenu. --isole évalue dans des conditions de référence
(journal vide, rien n'est enregistré) : le résultat est le même sur tout poste et en CI.
"""

from __future__ import annotations

import argparse
import dataclasses
import secrets
import sys
from pathlib import Path

from copilote.application import creer_application
from copilote.comptes import DepotUtilisateursMemoire
from copilote.config import Config, ModeLLM
from copilote.evaluation import Campagne, DepotEvaluationsMemoire, en_markdown
from copilote.fournisseurs import libelle_redacteur
from copilote.journal import DepotMemoire


def _liste(valeur: str) -> list[str]:
    return [v.strip() for v in valeur.split(",") if v.strip()]


def ecrire_rapports(campagne: Campagne, dossier: Path) -> tuple[Path, Path]:
    dossier.mkdir(parents=True, exist_ok=True)
    base = dossier / f"evaluation-{campagne.lancee_le:%Y%m%d-%H%M%S}"
    json_ = base.with_suffix(".json")
    markdown = base.with_suffix(".md")
    json_.write_text(campagne.model_dump_json(indent=2), encoding="utf-8")
    markdown.write_text(en_markdown(campagne), encoding="utf-8")
    return json_, markdown


def _fr(valeur: float, decimales: int = 1) -> str:
    return f"{valeur:.{decimales}f}".replace(".", ",")


def resume_console(campagne: Campagne) -> str:
    lignes = [f"Évaluation — version du prompt {campagne.empreinte_prompt} — {len(campagne.fiches)} fiches"]
    for s in campagne.syntheses:
        cout = "" if s.cout_par_fiche_usd is None else f" · {_fr(s.cout_par_fiche_usd, 4)} $/fiche"
        lignes.append(
            f"  {libelle_redacteur(s.redacteur):<18} score {_fr(s.score_global):>5}  "
            f"(fidélité {_fr(s.score_fidelite)}, couverture {_fr(s.score_couverture)}, format {_fr(s.score_format)})  "
            f"{s.fiches_sans_defaut}/{s.nb_fiches} sans défaut · repli {s.taux_repli_pct} %{cout}"
        )
    return "\n".join(lignes)


def main(arguments: list[str] | None = None) -> int:
    config = Config.depuis_environnement()
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument(
        "--redacteurs",
        type=_liste,
        help=f"parmi {', '.join(m.value for m in ModeLLM if m is not ModeLLM.AUTO)} (défaut : tous ceux disponibles)",
    )
    parser.add_argument("--clients", type=_liste, help="identifiants séparés par des virgules (défaut : tous)")
    parser.add_argument("--sortie", type=Path, default=config.dossier_donnees / "evaluations")
    parser.add_argument("--score-minimum", type=float, help="échoue si un rédacteur IA obtient un score inférieur")
    parser.add_argument("--sans-historique", action="store_true", help="ne pas enregistrer la campagne")
    parser.add_argument(
        "--isole", action="store_true", help="conditions de référence : journal vide, rien d'enregistré (CI)"
    )
    args = parser.parse_args(arguments)

    # Aucune session utilisateur n'est ouverte ici : un secret jetable évite l'avertissement de démarrage.
    secret = config.securite.secret_session or secrets.token_urlsafe(48)
    securite = dataclasses.replace(config.securite, secret_session=secret)
    config = dataclasses.replace(config, securite=securite)
    if args.isole:
        application = creer_application(
            config,
            depot_journal=DepotMemoire(),
            depot_utilisateurs=DepotUtilisateursMemoire(),
            depot_evaluations=DepotEvaluationsMemoire(),
        )
    else:
        application = creer_application(config)
    service = application.evaluation
    redacteurs = [ModeLLM(r) for r in args.redacteurs] if args.redacteurs else service.redacteurs_disponibles

    def progression(faites: int, total: int) -> None:
        if sys.stderr.isatty():  # pas de compteur dans les journaux de CI
            print(f"\r  {faites}/{total} fiches évaluées", end="", file=sys.stderr, flush=True)

    campagne = service.executer(redacteurs, args.clients, progression=progression, enregistrer=not args.sans_historique)
    if sys.stderr.isatty():
        print(file=sys.stderr)
    json_, markdown = ecrire_rapports(campagne, args.sortie)
    print(resume_console(campagne))
    print(f"Rapports : {markdown} et {json_}")

    if args.score_minimum is not None:
        sous_le_seuil = [
            s for s in campagne.syntheses if s.redacteur is not ModeLLM.REPLI and s.score_global < args.score_minimum
        ]
        for s in sous_le_seuil:
            print(f"ÉCHEC : {libelle_redacteur(s.redacteur)} à {_fr(s.score_global)} < {_fr(args.score_minimum)}")
        return 1 if sous_le_seuil else 0
    return 0


if __name__ == "__main__":
    sys.exit(main())
