"""Diagnostic des données en ligne de commande, avec la configuration de l'environnement.

    python -m copilote.diagnostic            # rapport lisible
    python -m copilote.diagnostic --json     # rapport complet en JSON
    DATASOURCE=http DATAHUB_URL=… DATAHUB_TOKEN=… python -m copilote.diagnostic

Code de sortie : 0 si conforme ou à surveiller, 1 si des corrections sont
nécessaires, 2 si la lecture est impossible (datahub injoignable, jeton refusé,
réponse non conforme au contrat…).
"""

from __future__ import annotations

import argparse
import sys

from copilote.analyses import REGLES_PAR_DEFAUT
from copilote.config import Config
from copilote.datahub import creer_source, sans_cache

from .modeles import Gravite, RapportDiagnostic, StatutDiagnostic, Traitement
from .rapport import diagnostiquer

LIBELLES_STATUT = {
    StatutDiagnostic.CONFORME: "CONFORME",
    StatutDiagnostic.A_SURVEILLER: "À SURVEILLER",
    StatutDiagnostic.A_CORRIGER: "À CORRIGER",
    StatutDiagnostic.LECTURE_IMPOSSIBLE: "LECTURE IMPOSSIBLE",
}
CODES_SORTIE = {
    StatutDiagnostic.CONFORME: 0,
    StatutDiagnostic.A_SURVEILLER: 0,
    StatutDiagnostic.A_CORRIGER: 1,
    StatutDiagnostic.LECTURE_IMPOSSIBLE: 2,
}


def formater(rapport: RapportDiagnostic) -> str:
    """Rapport texte, lisible dans un terminal ou un courriel."""
    lignes = [
        f"Diagnostic des données — source « {rapport.source} » — {rapport.genere_le:%d/%m/%Y %H:%M}",
        f"Statut : {LIBELLES_STATUT[rapport.statut]} — {rapport.resume}",
        "",
        "Connexion",
    ]
    for mesure in rapport.connexion:
        etat = f"{mesure.volume} éléments" if mesure.erreur is None else f"ERREUR : {mesure.erreur}"
        lignes.append(f"  {mesure.libelle:<26} {mesure.duree_ms:>6} ms   {etat}")
    if rapport.contrat:
        lignes += ["", "Contrat d'interface"]
        lignes += [f"  {'✓' if v.reussie else '✗'} {v.libelle} — {v.detail}" for v in rapport.contrat]
    en_defaut = [r for r in rapport.qualite if r.nombre]
    if rapport.qualite:
        sans_anomalie = len(rapport.qualite) - len(en_defaut)
        lignes += ["", f"Qualité des données ({sans_anomalie}/{len(rapport.qualite)} règles sans anomalie)"]
    for regle in sorted(en_defaut, key=lambda r: list(Gravite).index(r.gravite)):
        traitement = "écarté des analyses" if regle.traitement is Traitement.ECARTE else "à corriger dans l'ERP"
        lignes.append(f"  [{regle.gravite.value}] {regle.libelle} : {regle.nombre} ({traitement})")
        lignes += [f"      {e.identifiant} — {e.detail}" for e in regle.exemples]
    return "\n".join(lignes)


def main(arguments: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--json", action="store_true", help="rapport complet au format JSON")
    args = parser.parse_args(arguments)
    config = Config.depuis_environnement()
    rapport = diagnostiquer(sans_cache(creer_source(config)), REGLES_PAR_DEFAUT.periode_analyse_jours)
    print(rapport.model_dump_json(indent=2) if args.json else formater(rapport))
    return CODES_SORTIE[rapport.statut]


if __name__ == "__main__":
    sys.exit(main())
