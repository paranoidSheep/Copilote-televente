"""Lancement du serveur : `python -m copilote [--hote 0.0.0.0] [--port 8000] [--reload]`."""

from __future__ import annotations

import argparse
import os

import uvicorn

from copilote.config import Config
from copilote.journaux import configurer_journaux


def main() -> None:
    parser = argparse.ArgumentParser(description="Copilote télévente")
    parser.add_argument("--hote", default=os.environ.get("HOTE", "127.0.0.1"))
    parser.add_argument("--port", type=int, default=int(os.environ.get("PORT", "8000")))
    parser.add_argument("--reload", action="store_true", help="recharger à chaque modification du code")
    parser.add_argument(
        "--ips-proxy",
        default=os.environ.get("FORWARDED_ALLOW_IPS", "127.0.0.1"),
        help="adresses du proxy (Caddy) dont on accepte les en-têtes X-Forwarded-*",
    )
    args = parser.parse_args()
    configurer_journaux(Config.depuis_environnement().format_journaux)
    uvicorn.run(
        "copilote.api.app:creer_app",
        factory=True,
        host=args.hote,
        port=args.port,
        reload=args.reload,
        proxy_headers=True,
        forwarded_allow_ips=args.ips_proxy,
        log_config=None,  # journaux configurés par le copilote
    )


if __name__ == "__main__":
    main()
