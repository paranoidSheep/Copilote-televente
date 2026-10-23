"""Sauvegarde à chaud des bases SQLite du copilote (journal d'appels et comptes).

    python -m scripts.sauvegarder [--destination var/sauvegardes] [--garder 14]

Utilise l'API de sauvegarde de SQLite : cohérente même si l'application écrit
pendant la copie. Les sauvegardes les plus anciennes au-delà de --garder sont
supprimées. À planifier chaque nuit (cron), voir docs/DEPLOIEMENT.md.
"""

from __future__ import annotations

import argparse
import sqlite3
from contextlib import closing
from datetime import datetime
from pathlib import Path

from copilote.config import Config


def sauvegarder(source: Path, destination: Path, horodatage: str) -> Path | None:
    if not source.exists():
        return None
    cible = destination / f"{source.stem}-{horodatage}.sqlite3"
    # `closing` : le `with` d'une connexion sqlite3 valide la transaction mais ne ferme pas la connexion.
    with closing(sqlite3.connect(source)) as origine, closing(sqlite3.connect(cible)) as copie:
        origine.backup(copie)
    return cible


def purger(destination: Path, prefixe: str, garder: int) -> list[Path]:
    fichiers = sorted(destination.glob(f"{prefixe}-*.sqlite3"))
    a_supprimer = fichiers[:-garder] if garder > 0 else []
    for fichier in a_supprimer:
        fichier.unlink()
    return a_supprimer


def main() -> None:
    config = Config.depuis_environnement()
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--destination", type=Path, default=config.dossier_donnees / "sauvegardes")
    parser.add_argument("--garder", type=int, default=14, help="nombre de sauvegardes conservées par base")
    args = parser.parse_args()
    args.destination.mkdir(parents=True, exist_ok=True)
    horodatage = datetime.now().strftime("%Y%m%d-%H%M%S")
    for base in (config.chemin_journal, config.chemin_utilisateurs):
        cible = sauvegarder(base, args.destination, horodatage)
        if cible is None:
            print(f"{base} : absente, ignorée")
            continue
        supprimees = purger(args.destination, base.stem, args.garder)
        print(f"{base} -> {cible} ({len(supprimees)} ancienne(s) sauvegarde(s) supprimée(s))")


if __name__ == "__main__":
    main()
