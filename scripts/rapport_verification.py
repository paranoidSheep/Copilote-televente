"""Rapport de vérification : exécute tous les contrôles qualité et produit une page HTML.

    python -m scripts.rapport_verification --titre "Étape 1" --sortie docs/captures/etape-1/verification.html
    python -m scripts.rapport_verification ... --capture docs/captures/etape-1/00-verification.png

Contrôles : lint et formatage (ruff), typage strict (mypy), tests et couverture
(pytest), cassettes de l'IA simulée, types TypeScript, compilation du frontend.
L'option --capture enregistre une image de la page avec Chromium (si disponible).
"""

from __future__ import annotations

import argparse
import html
import os
import re
import shutil
import subprocess
import sys
import tempfile
import time
import xml.etree.ElementTree as ET
from collections import Counter
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path

RACINE = Path(__file__).resolve().parent.parent
CHROMIUM_PAR_DEFAUT = "/opt/pw-browsers/chromium-1243/chrome-linux64/chrome"


@dataclass(frozen=True)
class Controle:
    nom: str
    commande: list[str]
    dossier: Path = RACINE


@dataclass(frozen=True)
class Resultat:
    nom: str
    reussi: bool
    duree_s: float
    resume: str


def executer(controle: Controle) -> tuple[Resultat, str]:
    debut = time.perf_counter()
    processus = subprocess.run(controle.commande, cwd=controle.dossier, capture_output=True, text=True, check=False)
    sortie = (processus.stdout + processus.stderr).strip()
    lignes = [l for l in sortie.splitlines() if l.strip()]
    # Pour pytest, la ligne utile est le bilan (« 164 passed in 15.9s »), pas la dernière ligne de couverture.
    bilan = next((l for l in reversed(lignes) if re.search(r"\d+ (passed|failed)", l)), None)
    derniere = bilan or (lignes[-1] if lignes else "(aucune sortie)")
    return Resultat(controle.nom, processus.returncode == 0, time.perf_counter() - debut, derniere), sortie


def tests_par_fichier(junit: Path) -> Counter[str]:
    racine = ET.parse(junit).getroot()
    compte: Counter[str] = Counter()
    for cas in racine.iter("testcase"):
        compte[cas.get("classname", "?").split(".")[1] if "." in cas.get("classname", "") else "?"] += 1
    return compte


def page_html(titre: str, resultats: list[Resultat], par_fichier: Counter[str], couverture: str | None) -> str:
    ok = all(r.reussi for r in resultats)
    lignes = "\n".join(
        f"<tr><td>{'✅' if r.reussi else '❌'}</td><td>{html.escape(r.nom)}</td>"
        f"<td class='n'>{r.duree_s:.1f} s</td><td><code>{html.escape(r.resume[:140])}</code></td></tr>"
        for r in resultats
    )
    fichiers = "\n".join(
        f"<tr><td><code>tests/{html.escape(f)}.py</code></td><td class='n'>{n}</td></tr>"
        for f, n in sorted(par_fichier.items())
    )
    total = sum(par_fichier.values())
    statut = "Tous les contrôles sont au vert" if ok else "Échec"
    return f"""<!doctype html><html lang="fr"><head><meta charset="utf-8"><title>{html.escape(titre)}</title>
<style>
 body {{ font: 15px/1.45 system-ui, sans-serif; background: #f2f4f3; color: #18211d; margin: 0; padding: 28px; }}
 .carte {{ background: #fff; border: 1px solid #dde4e1; border-radius: 14px; padding: 18px 20px; margin-bottom: 14px; }}
 h1 {{ font-size: 1.35rem; margin: 0 0 4px; }} h2 {{ font-size: .8rem; text-transform: uppercase;
 letter-spacing: .06em; color: #5a6762; margin: 0 0 10px; }}
 .statut {{ display: inline-block; padding: 4px 10px; border-radius: 8px; font-weight: 700;
 background: {"#e3f4ea" if ok else "#fbebe5"}; color: {"#1f7a46" if ok else "#b3401d"}; }}
 table {{ width: 100%; border-collapse: collapse; }} td, th {{ padding: 7px 6px; border-bottom: 1px solid #dde4e1;
 text-align: left; vertical-align: top; }} .n {{ text-align: right; white-space: nowrap; }}
 code {{ font-size: .82rem; color: #3b4844; }} .kpis {{ display: flex; gap: 10px; flex-wrap: wrap; margin-top: 12px; }}
 .kpi {{ background: #f2f4f3; border-radius: 10px; padding: 10px 14px; min-width: 130px; }}
 .kpi b {{ font-size: 1.3rem; display: block; }}
</style></head><body>
<div class="carte"><h1>{html.escape(titre)}</h1>
<div>{datetime.now():%d/%m/%Y %H:%M} · <span class="statut">{statut}</span></div>
<div class="kpis"><div class="kpi"><b>{total}</b>tests</div><div class="kpi"><b>{couverture or "—"}</b>couverture</div>
<div class="kpi"><b>{sum(r.reussi for r in resultats)}/{len(resultats)}</b>contrôles réussis</div></div></div>
<div class="carte"><h2>Contrôles</h2><table>{lignes}</table></div>
<div class="carte"><h2>Tests par fichier</h2><table>{fichiers}</table></div>
</body></html>"""


def capturer(page: Path, image: Path, chromium: str) -> None:
    image.parent.mkdir(parents=True, exist_ok=True)
    subprocess.run(
        [
            chromium,
            "--headless=new",
            "--no-sandbox",
            "--disable-gpu",
            "--hide-scrollbars",
            "--window-size=1100,1500",
            f"--screenshot={image}",
            page.resolve().as_uri(),
        ],
        capture_output=True,
        check=True,
        timeout=60,
    )


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--titre", default="Vérification du copilote télévente")
    parser.add_argument("--sortie", type=Path, default=RACINE / "var" / "verification.html")
    parser.add_argument("--capture", type=Path)
    parser.add_argument("--chromium", default=os.environ.get("CHROMIUM", CHROMIUM_PAR_DEFAUT))
    args = parser.parse_args()

    with tempfile.TemporaryDirectory() as temporaire:
        junit = Path(temporaire) / "junit.xml"
        python = sys.executable
        controles = [
            Controle("Lint (ruff check)", ["ruff", "check", "."]),
            Controle("Formatage (ruff format)", ["ruff", "format", "--check", "."]),
            Controle("Typage strict (mypy --strict)", [python, "-m", "mypy"]),
            Controle(
                "Tests et couverture (pytest)",
                [python, "-m", "pytest", "-q", "--cov", "--cov-report=term", f"--junitxml={junit}"],
            ),
            Controle("Cassettes de l'IA simulée", [python, "-m", "scripts.cassettes", "verifier"]),
            Controle("Types TypeScript à jour", [python, "-m", "scripts.generer_types_ts", "--verifier"]),
        ]
        if shutil.which("tsc"):
            controles.append(
                Controle(
                    "Compilation TypeScript stricte", ["tsc", "-p", "tsconfig.json", "--noEmit"], RACINE / "frontend"
                )
            )
        resultats, couverture = [], None
        for controle in controles:
            resultat, sortie = executer(controle)
            resultats.append(resultat)
            print(
                f"{'OK ' if resultat.reussi else 'KO '} {resultat.nom} ({resultat.duree_s:.1f} s) — {resultat.resume}"
            )
            if controle.nom.startswith("Tests") and (trouve := re.search(r"^TOTAL.*?(\d+%)$", sortie, re.M)):
                couverture = trouve.group(1)
        par_fichier = tests_par_fichier(junit) if junit.exists() else Counter()

    args.sortie.parent.mkdir(parents=True, exist_ok=True)
    args.sortie.write_text(page_html(args.titre, resultats, par_fichier, couverture), encoding="utf-8")
    print(f"Rapport : {args.sortie}")
    if args.capture:
        capturer(args.sortie, args.capture, args.chromium)
        print(f"Capture : {args.capture}")
    return 0 if all(r.reussi for r in resultats) else 1


if __name__ == "__main__":
    sys.exit(main())
