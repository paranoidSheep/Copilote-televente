"""Administration des comptes utilisateurs, en ligne de commande.

    python -m copilote.admin creer julie --nom "Julie Moreau" --role televendeur
    python -m copilote.admin lister
    python -m copilote.admin mot-de-passe julie
    python -m copilote.admin desactiver julie        # (ou « activer »)
    python -m copilote.admin demo                    # un compte par télévendeur + un responsable

Le mot de passe est demandé de façon masquée ; pour l'automatisation, il peut
être lu dans la variable d'environnement COPILOTE_MOT_DE_PASSE.
Dans le conteneur : `docker compose exec copilote python -m copilote.admin …`.
"""

from __future__ import annotations

import argparse
import getpass
import os
import sys
import unicodedata

from copilote.comptes import (
    DepotUtilisateursSQLite,
    Role,
    ServiceComptes,
    UtilisateurExistant,
    generer_mot_de_passe,
)
from copilote.config import Config
from copilote.datahub import creer_source
from copilote.domaine import ErreurCopilote


def _service(config: Config) -> ServiceComptes:
    # Administration seulement : aucune session n'est ouverte, donc pas de signataire.
    return ServiceComptes(DepotUtilisateursSQLite(config.chemin_utilisateurs))


def _mot_de_passe() -> str:
    if valeur := os.environ.get("COPILOTE_MOT_DE_PASSE"):
        return valeur
    premier = getpass.getpass("Mot de passe : ")
    if getpass.getpass("Confirmation : ") != premier:
        raise ErreurCopilote("Les deux saisies ne correspondent pas.")
    return premier


def identifiant_depuis_nom(nom: str) -> str:
    """« Karim Bensaïd » -> « karim.bensaid »"""
    sans_accents = unicodedata.normalize("NFKD", nom).encode("ascii", "ignore").decode()
    return ".".join(sans_accents.lower().split())


def commande_demo(service: ServiceComptes, config: Config) -> None:
    """Crée un compte par télévendeur présent dans les données, plus un responsable."""
    vendeurs = sorted({c.commercial for c in creer_source(config).get_clients()})
    comptes = [(identifiant_depuis_nom(v), v, Role.TELEVENDEUR) for v in vendeurs]
    comptes.append(("responsable", "Responsable télévente", Role.RESPONSABLE))
    print("Comptes de démonstration (notez les mots de passe, ils ne seront plus affichés) :\n")
    for identifiant, nom, role in comptes:
        mot_de_passe = generer_mot_de_passe()
        try:
            service.creer(identifiant, nom, role, mot_de_passe)
            print(f"  {identifiant:<18} {role:<12} {mot_de_passe}")
        except UtilisateurExistant:
            print(f"  {identifiant:<18} {role:<12} (existe déjà, inchangé)")


def main(arguments: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sous = parser.add_subparsers(dest="commande", required=True)
    creer = sous.add_parser("creer", help="créer un compte")
    creer.add_argument("identifiant")
    creer.add_argument("--nom", required=True, help="nom affiché (pour un télévendeur : son nom dans l'ERP)")
    creer.add_argument("--role", choices=[r.value for r in Role], default=Role.TELEVENDEUR.value)
    sous.add_parser("lister", help="lister les comptes")
    for nom in ("mot-de-passe", "activer", "desactiver"):
        sous.add_parser(nom).add_argument("identifiant")
    sous.add_parser("demo", help="créer les comptes de démonstration")
    args = parser.parse_args(arguments)

    config = Config.depuis_environnement()
    service = _service(config)
    try:
        match args.commande:
            case "creer":
                utilisateur = service.creer(args.identifiant, args.nom, Role(args.role), _mot_de_passe())
                print(f"Compte créé : {utilisateur.identifiant} ({utilisateur.role})")
            case "lister":
                for u in service.lister():
                    print(f"{u.identifiant:<18} {u.role:<12} {'actif' if u.actif else 'désactivé':<10} {u.nom_affiche}")
            case "mot-de-passe":
                service.changer_mot_de_passe(args.identifiant, _mot_de_passe())
                print("Mot de passe modifié : les sessions ouvertes de ce compte sont fermées.")
            case "activer" | "desactiver":
                service.activer(args.identifiant, args.commande == "activer")
                print(f"Compte {args.identifiant} {'activé' if args.commande == 'activer' else 'désactivé'}.")
            case "demo":
                commande_demo(service, config)
    except ErreurCopilote as exc:
        print(f"Erreur : {exc}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
