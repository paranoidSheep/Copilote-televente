"""Exporte le contrat d'interface du datahub (schéma OpenAPI du simulateur).

    python -m scripts.exporter_contrat_datahub            # écrit docs/contrat-datahub.json
    python -m scripts.exporter_contrat_datahub --verifier # échoue si le fichier n'est pas à jour (CI)

Ce fichier est à transmettre à l'équipe du datahub : il décrit exactement les
ressources, paramètres et champs que `HttpDataSource` sait lire. Il s'ouvre
dans n'importe quel outil OpenAPI (Swagger Editor, Postman, Insomnia…).
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from copilote.datahub.simulateur import creer_simulateur

SORTIE = Path(__file__).resolve().parent.parent / "docs" / "contrat-datahub.json"


def generer() -> str:
    schema = creer_simulateur().openapi()
    schema["servers"] = [{"url": "https://datahub.exemple.local/api", "description": "À remplacer par l'URL réelle"}]
    schema["components"]["securitySchemes"] = {"jeton": {"type": "http", "scheme": "bearer"}}
    schema["security"] = [{"jeton": []}]
    return json.dumps(schema, ensure_ascii=False, indent=2) + "\n"


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--verifier", action="store_true")
    args = parser.parse_args()
    contenu = generer()
    if args.verifier:
        if not SORTIE.exists() or SORTIE.read_text(encoding="utf-8") != contenu:
            print(f"{SORTIE} n'est pas à jour : lancez `python -m scripts.exporter_contrat_datahub`.")
            return 1
        print("Contrat d'interface du datahub à jour.")
        return 0
    SORTIE.write_text(contenu, encoding="utf-8")
    print(f"Contrat écrit dans {SORTIE}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
