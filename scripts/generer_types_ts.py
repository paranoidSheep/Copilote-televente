"""Génère les types TypeScript du frontend à partir du schéma OpenAPI de l'API.

    python -m scripts.generer_types_ts            # écrit frontend/src/types-api.ts
    python -m scripts.generer_types_ts --verifier # échoue si le fichier n'est pas à jour (CI)

Le frontend et le backend partagent ainsi exactement les mêmes structures :
toute évolution d'un modèle pydantic se répercute à la compilation TypeScript.
"""

from __future__ import annotations

import argparse
import sys
from collections.abc import Mapping
from pathlib import Path

from pydantic import JsonValue

from copilote.api import creer_app
from copilote.application import creer_application
from copilote.comptes import DepotUtilisateursMemoire
from copilote.config import Config, ConfigSecurite
from copilote.journal import DepotMemoire

SORTIE = Path(__file__).resolve().parent.parent / "frontend" / "src" / "types-api.ts"
IGNORES = {"HTTPValidationError", "ValidationError"}

type Schema = Mapping[str, JsonValue]


def nom_type(reference: str) -> str:
    return reference.rsplit("/", 1)[-1].replace("-", "_")


def vers_ts(schema: JsonValue) -> str:
    """Traduit un schéma JSON en expression de type TypeScript."""
    if not isinstance(schema, dict):
        return "unknown"
    if isinstance(ref := schema.get("$ref"), str):
        return nom_type(ref)
    if isinstance(variantes := schema.get("anyOf"), list):
        return " | ".join(dict.fromkeys(vers_ts(v) for v in variantes))
    if isinstance(enum := schema.get("enum"), list):
        return " | ".join(f'"{v}"' if isinstance(v, str) else str(v) for v in enum)
    if "const" in schema:
        const = schema["const"]
        return f'"{const}"' if isinstance(const, str) else str(const)
    match schema.get("type"):
        case "string":
            return "string"
        case "integer" | "number":
            return "number"
        case "boolean":
            return "boolean"
        case "null":
            return "null"
        case "array":
            element = vers_ts(schema.get("items", {}))
            return f"({element})[]" if "|" in element else f"{element}[]"
        case "object":
            return objet_ts(schema)
    return "unknown"


def objet_ts(schema: Schema) -> str:
    proprietes = schema.get("properties")
    if isinstance(proprietes, dict) and proprietes:
        requis = schema.get("required", [])
        requis = requis if isinstance(requis, list) else []
        lignes = [
            f"  {nom}{'' if nom in requis else '?'}: {vers_ts(sous_schema)};" for nom, sous_schema in proprietes.items()
        ]
        return "{\n" + "\n".join(lignes) + "\n}"
    valeurs = schema.get("additionalProperties")
    if isinstance(valeurs, dict):
        cles = schema.get("propertyNames")
        if isinstance(cles, dict) and cles:
            return f"Partial<Record<{vers_ts(cles)}, {vers_ts(valeurs)}>>"
        return f"Record<string, {vers_ts(valeurs)}>"
    return "Record<string, unknown>"


def generer() -> str:
    # Application éphémère, sans effet de bord : seul le schéma OpenAPI est utilisé.
    application = creer_application(
        Config(securite=ConfigSecurite(secret_session="generation-des-types-typescript-sans-session")),
        depot_journal=DepotMemoire(),
        depot_utilisateurs=DepotUtilisateursMemoire(),
    )
    schemas = creer_app(application).openapi()["components"]["schemas"]
    blocs = [
        "// Fichier GÉNÉRÉ par `python -m scripts.generer_types_ts` à partir du schéma OpenAPI.",
        "// Ne pas modifier à la main : modifier les modèles pydantic puis relancer le script.",
        "",
    ]
    for nom in sorted(schemas):
        if nom in IGNORES:
            continue
        schema = schemas[nom]
        description = schema.get("description")
        if isinstance(description, str):
            blocs.append("/** " + description.strip().replace("\n", " ").replace("*/", "*\\/") + " */")
        expression = vers_ts(schema)
        if schema.get("type") == "object" and expression.startswith("{"):
            blocs.append(f"export interface {nom_type(nom)} {expression}")
        else:
            blocs.append(f"export type {nom_type(nom)} = {expression};")
        blocs.append("")
    return "\n".join(blocs)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--verifier", action="store_true")
    args = parser.parse_args()
    contenu = generer()
    if args.verifier:
        if not SORTIE.exists() or SORTIE.read_text(encoding="utf-8") != contenu:
            print(f"{SORTIE} n'est pas à jour : lancez `python -m scripts.generer_types_ts`.")
            return 1
        print("Types TypeScript à jour.")
        return 0
    SORTIE.parent.mkdir(parents=True, exist_ok=True)
    SORTIE.write_text(contenu, encoding="utf-8")
    print(f"Types écrits dans {SORTIE}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
