"""Export CSV des commandes acceptées, pour saisie (ou import manuel) dans l'ERP.

Format pensé pour Excel en français : séparateur « ; », virgule décimale et
marque d'ordre des octets (BOM) UTF-8 pour que les accents s'affichent. Le
copilote n'écrit toujours rien dans l'ERP : ce fichier est remis au télévendeur.
"""

from __future__ import annotations

import csv
import io
from collections.abc import Iterable, Mapping

from .modeles import CompteRendu, Reponse

COLONNES = [
    "Date",
    "Heure",
    "Télévendeur",
    "Code client",
    "Client",
    "Code produit",
    "Libellé",
    "Quantité",
    "Unité",
    "Prix unitaire HT",
    "Remise %",
    "Prix net HT",
    "Montant HT",
    "Origine",
    "N° compte-rendu",
]


def _texte(valeur: str) -> str:
    """Neutralise l'injection de formule : Excel interpréterait « =… », « +… », « -… » ou « @… »."""
    return f"'{valeur}" if valeur[:1] in {"=", "+", "-", "@", "\t", "\r"} else valeur


def _decimal(valeur: float) -> str:
    return f"{valeur:.2f}".replace(".", ",")


def _quantite(valeur: float) -> str:
    return f"{valeur:g}".replace(".", ",")


def commandes_csv(comptes_rendus: Iterable[CompteRendu], noms_clients: Mapping[str, str]) -> str:
    """Une ligne par produit accepté, dans l'ordre chronologique des appels."""
    tampon = io.StringIO()
    tampon.write("﻿")  # BOM : Excel reconnaît l'UTF-8
    ecrivain = csv.writer(tampon, delimiter=";", lineterminator="\r\n")
    ecrivain.writerow(COLONNES)
    for cr in sorted(comptes_rendus, key=lambda c: (c.cree_le, c.id)):
        for ligne in cr.lignes:
            if ligne.reponse is not Reponse.ACCEPTE:
                continue
            ecrivain.writerow(
                [
                    f"{cr.cree_le:%d/%m/%Y}",
                    f"{cr.cree_le:%H:%M}",
                    _texte(cr.televendeur),
                    _texte(cr.client_id),
                    _texte(noms_clients.get(cr.client_id, "")),
                    _texte(ligne.code),
                    _texte(ligne.libelle),
                    _quantite(ligne.quantite),
                    _texte(ligne.unite),
                    _decimal(ligne.prix_unitaire_ht),
                    str(ligne.remise_pct),
                    _decimal(ligne.prix_net_ht),
                    _decimal(ligne.montant_ht),
                    ligne.origine.value,
                    str(cr.id),
                ]
            )
    return tampon.getvalue()
