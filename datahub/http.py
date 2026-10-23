"""Client REST pour le vrai datahub (SQUELETTE À COMPLÉTER).

Configuration par variables d'environnement :
- DATAHUB_URL    : URL de base de l'API, ex. https://datahub.mon-entreprise.local/api/v1
- DATAHUB_TOKEN  : jeton d'accès (envoyé en `Authorization: Bearer …`)
- DATAHUB_TIMEOUT: délai max d'une requête en secondes (défaut : 10)

Ce client n'effectue QUE des requêtes GET : le datahub est en lecture seule et
le copilote ne doit jamais écrire dans l'ERP. La méthode `_get` est le seul
point de sortie réseau ; ne pas ajouter de POST/PUT/PATCH/DELETE.

Les chemins d'API et la correspondance des champs ci-dessous sont des
HYPOTHÈSES : chaque `TODO` est à confirmer avec l'équipe du datahub (voir la
section « Brancher le vrai datahub » du README).
"""

from __future__ import annotations

import os
from datetime import date
from typing import Any

import httpx

from .base import Client, ClientIntrouvable, Commande, DataSource, DataSourceError, LigneCommande, Lot, Produit

MAX_PAGES = 1000  # garde-fou contre une pagination qui ne se terminerait jamais


class HttpDataSource(DataSource):
    nom = "http"

    def __init__(
        self,
        base_url: str | None = None,
        token: str | None = None,
        timeout: float | None = None,
        transport: httpx.BaseTransport | None = None,  # injecté par les tests
    ) -> None:
        base_url = base_url or os.environ.get("DATAHUB_URL")
        token = token or os.environ.get("DATAHUB_TOKEN")
        if not base_url:
            raise DataSourceError("DATAHUB_URL n'est pas défini : impossible d'utiliser DATASOURCE=http.")
        if not token:
            raise DataSourceError("DATAHUB_TOKEN n'est pas défini : impossible d'utiliser DATASOURCE=http.")
        timeout = timeout or float(os.environ.get("DATAHUB_TIMEOUT", "10"))

        # TODO(datahub) : confirmer le mode d'authentification (Bearer, clé d'API
        # dans un en-tête dédié, certificat client…).
        self._http = httpx.Client(
            base_url=base_url.rstrip("/"),
            headers={"Authorization": f"Bearer {token}", "Accept": "application/json"},
            timeout=timeout,
            transport=transport,
        )

    # -- Accès réseau (lecture seule) ----------------------------------------

    def _get(self, chemin: str, params: dict[str, Any] | None = None) -> Any:
        """Unique point d'accès réseau : requête GET, renvoie le JSON décodé."""
        # Paramètres vides ignorés ; `None` (et non {}) pour ne pas écraser la query string
        # d'une URL de pagination déjà complète (ex. /clients?page=2).
        filtres = {k: v for k, v in (params or {}).items() if v is not None} or None
        try:
            reponse = self._http.get(chemin, params=filtres)
        except httpx.HTTPError as exc:
            raise DataSourceError(f"Datahub injoignable ({chemin}) : {exc}") from exc
        if reponse.status_code == 404:
            raise ClientIntrouvable(f"Ressource introuvable sur le datahub : {chemin}")
        if reponse.is_error:
            raise DataSourceError(f"Erreur datahub {reponse.status_code} sur {chemin} : {reponse.text[:200]}")
        return reponse.json()

    def _get_liste(self, chemin: str, params: dict[str, Any] | None = None) -> list[dict]:
        """GET sur une ressource de type liste.

        TODO(datahub) : gérer la pagination réelle. Hypothèse actuelle : la réponse
        est soit une liste JSON, soit un objet {"items": [...], "next": url|null}.
        """
        donnees = self._get(chemin, params)
        if isinstance(donnees, list):
            return donnees
        elements = list(donnees.get("items", []))
        suivant = donnees.get("next")
        pages = 1
        while suivant:  # pagination par lien « next » (à confirmer)
            pages += 1
            if pages > MAX_PAGES:
                raise DataSourceError(f"Pagination anormalement longue sur {chemin} (> {MAX_PAGES} pages)")
            page = self._get(suivant)
            elements.extend(page.get("items", []))
            suivant = page.get("next")
        return elements

    # -- Implémentation de l'interface DataSource ----------------------------

    def get_clients(self) -> list[Client]:
        # TODO(datahub) : chemin exact et filtre « clients actifs » éventuel.
        return [_vers_client(d) for d in self._get_liste("/clients")]

    def get_client(self, client_id: str) -> Client:
        return _vers_client(self._get(f"/clients/{client_id}"))

    def get_order_history(self, client_id: str | None = None, depuis: date | None = None) -> list[Commande]:
        # TODO(datahub) : nom des paramètres de filtre ; s'assurer que les lignes
        # de commande sont incluses (sinon un appel par commande sera nécessaire).
        params = {"client_id": client_id, "depuis": depuis.isoformat() if depuis else None}
        commandes = [_vers_commande(d) for d in self._get_liste("/commandes", params)]
        return sorted(commandes, key=lambda c: (c.date, c.id))

    def get_products(self) -> list[Produit]:
        # TODO(datahub) : mettre en cache (le catalogue change peu) pour limiter les appels.
        return [_vers_produit(d) for d in self._get_liste("/produits")]

    def get_stock(self) -> list[Lot]:
        # TODO(datahub) : ne garder que le stock disponible (hors réservé / bloqué qualité).
        return [_vers_lot(d) for d in self._get_liste("/stock/lots")]


# ---------------------------------------------------------------------------
# Correspondance format datahub -> objets métier
# TODO(datahub) : adapter les noms de champs au format réel. Les valeurs par
# défaut ci-dessous supposent un format identique à celui du mock.
# ---------------------------------------------------------------------------


def _vers_client(d: dict) -> Client:
    return Client(
        id=str(d["id"]),
        nom=d["nom"],
        type=d.get("type", "Non renseigné"),  # TODO : code segment ERP -> libellé
        ville=d.get("ville", ""),
        contact=d.get("contact", ""),
        telephone=d.get("telephone", ""),
        commercial=d.get("commercial", ""),
    )


def _vers_produit(d: dict) -> Produit:
    return Produit(
        code=str(d["code"]),
        libelle=d["libelle"],
        categorie=d.get("categorie", "Divers"),
        famille=d["famille"],  # TODO : dériver de la température de stockage si absent
        unite=d.get("unite", "unité"),
        prix_unitaire_ht=float(d["prix_unitaire_ht"]),  # TODO : prix tarif ou prix client ?
        duree_vie_jours=int(d.get("duree_vie_jours", 0)),
    )


def _vers_commande(d: dict) -> Commande:
    return Commande(
        id=str(d["id"]),
        client_id=str(d["client_id"]),
        date=date.fromisoformat(d["date"][:10]),  # TODO : date de commande ou de livraison ?
        lignes=[
            LigneCommande(
                produit_code=str(l["produit_code"]),
                quantite=float(l["quantite"]),
                prix_unitaire_ht=float(l["prix_unitaire_ht"]),
            )
            for l in d.get("lignes", [])
        ],
    )


def _vers_lot(d: dict) -> Lot:
    return Lot(
        id=str(d["id"]),
        produit_code=str(d["produit_code"]),
        quantite=float(d["quantite"]),
        dlc=date.fromisoformat(d["dlc"][:10]),  # TODO : DLC ou DDM selon les produits
        date_reception=date.fromisoformat(d["date_reception"][:10]),
        entrepot=d.get("entrepot", ""),
    )
