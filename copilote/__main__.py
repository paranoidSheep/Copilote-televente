"""Lancement du serveur : `python -m copilote [--port 8000] [--reload]`."""

from __future__ import annotations

import argparse
import logging

import uvicorn


def main() -> None:
    parser = argparse.ArgumentParser(description="Copilote télévente")
    parser.add_argument("--hote", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=8000)
    parser.add_argument("--reload", action="store_true", help="recharger à chaque modification du code")
    args = parser.parse_args()
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s : %(message)s")
    uvicorn.run("copilote.api.app:creer_app", factory=True, host=args.hote, port=args.port, reload=args.reload)


if __name__ == "__main__":
    main()
