"""Client REST pour le vrai datahub (SQUELETTE À COMPLÉTER).

Ce client n'effectue QUE des requêtes GET : le datahub est en lecture seule et
le copilote n'écrit jamais dans l'ERP. `_get` est l'unique point de sortie
réseau ; ne pas ajouter de POST/PUT/PATCH/DELETE.

Les chemins d'API et la correspondance des champs sont des HYPOTHÈSES : chaque
`TODO(datahub)` est à confirmer avec l'équipe du datahub (voir le README,
section « Brancher le vrai datahub »).
"""

from __future__ import annotations

from collections.abc import Mapping
from datetime import date

import httpx
from pydantic import JsonValue

from copilote.config import ConfigDatahub
from copilote.domaine import (
    Client,
    ClientIntrouvable,
    Commande,
    ErreurConfiguration,
    ErreurSourceDonnees,
    Famille,
    LigneCommande,
    Lot,
    Produit,
)

from .base import DataSource

MAX_PAGES = 1000  # garde-fou contre une pagination qui ne se terminerait jamais

type ObjetJson = Mapping[str, JsonValue]


class _RessourceIntrouvable(ErreurSourceDonnees):
    """Réponse 404 du datahub (traduite en erreur métier par l'appelant)."""


class HttpDataSource(DataSource):
    nom = "http"

    def __init__(self, config: ConfigDatahub, transport: httpx.BaseTransport | None = None) -> None:
        if not config.url:
            raise ErreurConfiguration("DATAHUB_URL n'est pas défini : impossible d'utiliser DATASOURCE=http.")
        if not config.token:
            raise ErreurConfiguration("DATAHUB_TOKEN n'est pas défini : impossible d'utiliser DATASOURCE=http.")
        # TODO(datahub) : confirmer le mode d'authentification (Bearer, en-tête dédié, certificat…).
        self._http = httpx.Client(
            base_url=config.url.rstrip("/"),
            headers={"Authorization": f"Bearer {config.token}", "Accept": "application/json"},
            timeout=config.timeout_secondes,
            transport=transport,
        )

    # -- Accès réseau (lecture seule) -------------------------------------------

    def _get(self, chemin: str, params: Mapping[str, str | None] | None = None) -> JsonValue:
        """Unique point d'accès réseau : requête GET, renvoie le JSON décodé."""
        # Paramètres vides ignorés ; `None` (et non {}) pour ne pas écraser la query
        # string d'une URL de pagination déjà complète (ex. /clients?page=2).
        filtres = {k: v for k, v in (params or {}).items() if v is not None} or None
        try:
            reponse = self._http.get(chemin, params=filtres)
        except httpx.HTTPError as exc:
            raise ErreurSourceDonnees(f"Datahub injoignable ({chemin}) : {exc}") from exc
        if reponse.status_code == 404:
            raise _RessourceIntrouvable(f"Ressource introuvable sur le datahub : {chemin}")
        if reponse.is_error:
            raise ErreurSourceDonnees(f"Erreur datahub {reponse.status_code} sur {chemin} : {reponse.text[:200]}")
        donnees: JsonValue = reponse.json()
        return donnees

    def _get_objet(self, chemin: str) -> ObjetJson:
        donnees = self._get(chemin)
        if not isinstance(donnees, dict):
            raise ErreurSourceDonnees(f"Réponse inattendue sur {chemin} : objet JSON attendu")
        return donnees

    def _get_liste(self, chemin: str, params: Mapping[str, str | None] | None = None) -> list[ObjetJson]:
        """GET sur une ressource de type liste, pagination comprise.

        TODO(datahub) : hypothèse actuelle, la réponse est soit une liste JSON,
        soit un objet {"items": [...], "next": url | null}.
        """
        donnees = self._get(chemin, params)
        elements: list[JsonValue] = []
        pages = 1
        while True:
            if isinstance(donnees, list):
                elements.extend(donnees)
                break
            if not isinstance(donnees, dict):
                raise ErreurSourceDonnees(f"Réponse inattendue sur {chemin}")
            items = donnees.get("items", [])
            elements.extend(items if isinstance(items, list) else [])
            suivant = donnees.get("next")
            if not isinstance(suivant, str) or not suivant:
                break
            pages += 1
            if pages > MAX_PAGES:
                raise ErreurSourceDonnees(f"Pagination anormalement longue sur {chemin} (> {MAX_PAGES} pages)")
            donnees = self._get(suivant)
        objets: list[ObjetJson] = [e for e in elements if isinstance(e, dict)]
        if len(objets) != len(elements):
            raise ErreurSourceDonnees(f"Éléments non conformes dans la liste {chemin}")
        return objets

    # -- Implémentation de DataSource ---------------------------------------------

    def get_clients(self) -> list[Client]:
        # TODO(datahub) : chemin exact et filtre « clients actifs » éventuel.
        return [_vers_client(d) for d in self._get_liste("/clients")]

    def get_client(self, client_id: str) -> Client:
        try:
            return _vers_client(self._get_objet(f"/clients/{client_id}"))
        except _RessourceIntrouvable as exc:
            raise ClientIntrouvable(client_id) from exc

    def get_order_history(self, client_id: str | None = None, depuis: date | None = None) -> list[Commande]:
        # TODO(datahub) : nom des filtres ; vérifier que les lignes sont incluses.
        params = {"client_id": client_id, "depuis": depuis.isoformat() if depuis else None}
        commandes = [_vers_commande(d) for d in self._get_liste("/commandes", params)]
        return sorted(commandes, key=lambda c: (c.date, c.id))

    def get_products(self) -> list[Produit]:
        return [_vers_produit(d) for d in self._get_liste("/produits")]

    def get_stock(self) -> list[Lot]:
        # TODO(datahub) : ne garder que le stock disponible (hors réservé / bloqué qualité).
        return [_vers_lot(d) for d in self._get_liste("/stock/lots")]


# ---------------------------------------------------------------------------------
# Correspondance format datahub -> objets métier
# TODO(datahub) : adapter les noms de champs au format réel. Les valeurs par défaut
# supposent un format identique à celui du mock.
# ---------------------------------------------------------------------------------


def _texte(d: ObjetJson, cle: str, defaut: str | None = None) -> str:
    valeur = d.get(cle, defaut)
    if valeur is None:
        raise ErreurSourceDonnees(f"Champ obligatoire absent : {cle}")
    return str(valeur)


def _nombre(d: ObjetJson, cle: str, defaut: float | None = None) -> float:
    valeur = d.get(cle, defaut)
    if isinstance(valeur, bool) or not isinstance(valeur, int | float | str):
        raise ErreurSourceDonnees(f"Champ numérique invalide : {cle}")
    try:
        return float(valeur)
    except ValueError as exc:
        raise ErreurSourceDonnees(f"Champ numérique invalide : {cle}") from exc


def _date(d: ObjetJson, cle: str) -> date:
    return date.fromisoformat(_texte(d, cle)[:10])


def _vers_client(d: ObjetJson) -> Client:
    return Client(
        id=_texte(d, "id"),
        nom=_texte(d, "nom"),
        type=_texte(d, "type", "Non renseigné"),  # TODO : code segment ERP -> libellé
        ville=_texte(d, "ville", ""),
        contact=_texte(d, "contact", ""),
        telephone=_texte(d, "telephone", ""),
        commercial=_texte(d, "commercial", ""),
    )


def _vers_produit(d: ObjetJson) -> Produit:
    return Produit(
        code=_texte(d, "code"),
        libelle=_texte(d, "libelle"),
        categorie=_texte(d, "categorie", "Divers"),
        famille=Famille(_texte(d, "famille")),  # TODO : dériver de la température de stockage
        unite=_texte(d, "unite", "unité"),
        prix_unitaire_ht=_nombre(d, "prix_unitaire_ht"),  # TODO : prix tarif ou prix client ?
        duree_vie_jours=int(_nombre(d, "duree_vie_jours", 0)),
    )


def _vers_commande(d: ObjetJson) -> Commande:
    lignes = d.get("lignes", [])
    if not isinstance(lignes, list):
        raise ErreurSourceDonnees("Champ « lignes » invalide")
    return Commande(
        id=_texte(d, "id"),
        client_id=_texte(d, "client_id"),
        date=_date(d, "date"),  # TODO : date de commande ou de livraison ?
        lignes=tuple(
            LigneCommande(
                produit_code=_texte(ligne, "produit_code"),
                quantite=_nombre(ligne, "quantite"),
                prix_unitaire_ht=_nombre(ligne, "prix_unitaire_ht"),
            )
            for ligne in lignes
            if isinstance(ligne, dict)
        ),
    )


def _vers_lot(d: ObjetJson) -> Lot:
    return Lot(
        id=_texte(d, "id"),
        produit_code=_texte(d, "produit_code"),
        quantite=_nombre(d, "quantite"),
        dlc=_date(d, "dlc"),  # TODO : DLC ou DDM selon les produits
        date_reception=_date(d, "date_reception"),
        entrepot=_texte(d, "entrepot", ""),
    )
