"""Simulateur du datahub : implémentation de référence du contrat REST attendu par le copilote.

Il sert à trois choses :
1. éprouver dès maintenant le chemin `DATASOURCE=http` de bout en bout (réseau,
   jeton, pagination, correspondance des champs), sans attendre le vrai datahub ;
2. formaliser le contrat d'interface : son schéma OpenAPI est exporté dans
   `docs/contrat-datahub.json`, à transmettre à l'équipe du datahub ;
3. démontrer le contrôle qualité : l'option `--anomalies` injecte des défauts
   de données réalistes (références orphelines, prix nuls, DLC incohérentes…).

    python -m copilote.datahub.simulateur --port 8100 --jeton secret [--anomalies] [--latence-ms 80]
    DATASOURCE=http DATAHUB_URL=http://127.0.0.1:8100 DATAHUB_TOKEN=secret python -m copilote

Les données servies sont celles du jeu fictif (`MockDataSource`).
"""

from __future__ import annotations

import argparse
import asyncio
import datetime as dt
import hmac
import os
from dataclasses import dataclass
from datetime import timedelta
from typing import Annotated
from urllib.parse import urlencode

from fastapi import Depends, FastAPI, Header, HTTPException, Query, status
from pydantic import BaseModel, ConfigDict, Field

from copilote.domaine import Client, Commande, LigneCommande, Lot, Produit

from .base import DataSource
from .mock import MockDataSource

TAILLE_PAGE_PAR_DEFAUT = 200
TAILLE_PAGE_MAX = 1000

# Paramètres de pagination communs (au niveau du module : FastAPI doit pouvoir les résoudre).
Page = Annotated[int, Query(ge=1, description="Numéro de page, à partir de 1")]
Taille = Annotated[int, Query(ge=1, le=TAILLE_PAGE_MAX, description="Nombre d'éléments par page")]


# ---------------------------------------------------------------------------------
# Modèles du contrat (ce que le datahub doit renvoyer)
# ---------------------------------------------------------------------------------


class _Contrat(BaseModel):
    model_config = ConfigDict(frozen=True, json_schema_serialization_defaults_required=True)


class CommandeContrat(_Contrat):
    """Commande avec ses lignes (les lignes sont OBLIGATOIRES dans la réponse)."""

    id: str
    client_id: str
    date: dt.date = Field(description="Date de la commande (AAAA-MM-JJ)")
    lignes: list[LigneCommande]


PageSuivante = Annotated[
    str | None,
    Field(description="Chemin de la page suivante, filtres inclus (relatif à la racine) ; null si dernière page"),
]


class PageClients(_Contrat):
    items: list[Client]
    next: PageSuivante


class PageCommandes(_Contrat):
    items: list[CommandeContrat]
    next: PageSuivante


class PageProduits(_Contrat):
    items: list[Produit]
    next: PageSuivante


class PageLots(_Contrat):
    items: list[Lot]
    next: PageSuivante


# ---------------------------------------------------------------------------------
# Données servies (avec anomalies éventuelles)
# ---------------------------------------------------------------------------------


@dataclass(frozen=True)
class DonneesSimulees:
    clients: list[Client]
    produits: list[Produit]
    commandes: list[Commande]
    lots: list[Lot]
    date_du_jour: dt.date


def charger_donnees(source: DataSource, anomalies: bool) -> DonneesSimulees:
    donnees = DonneesSimulees(
        clients=source.get_clients(),
        produits=source.get_products(),
        commandes=source.get_order_history(),
        lots=source.get_stock(),
        date_du_jour=source.date_du_jour(),
    )
    return injecter_anomalies(donnees) if anomalies else donnees


def injecter_anomalies(d: DonneesSimulees) -> DonneesSimulees:
    """Défauts typiques d'un premier branchement, injectés de façon déterministe."""
    produits = list(d.produits)
    produits[3] = produits[3].model_copy(update={"prix_unitaire_ht": 0.0})  # prix manquant dans l'ERP
    produits[7] = produits[7].model_copy(update={"duree_vie_jours": 0})  # durée de vie non renseignée

    clients = list(d.clients)
    clients[5] = clients[5].model_copy(update={"commercial": ""})  # client sans télévendeur attribué
    clients[12] = clients[12].model_copy(update={"telephone": ""})  # numéro non renseigné
    clients.append(clients[0])  # doublon d'identifiant
    produits.append(produits[20].model_copy(update={"libelle": produits[20].libelle + " (ancienne fiche)"}))

    commandes = list(d.commandes)
    derniere = commandes[-1]
    commandes.append(  # référence à un produit inexistant dans le catalogue
        derniere.model_copy(
            update={
                "id": "CMD-ORPHELINE-1",
                "lignes": (LigneCommande(produit_code="ZZ999", quantite=3, prix_unitaire_ht=12.0),),
            }
        )
    )
    commandes.append(derniere.model_copy(update={"id": "CMD-CLIENT-INCONNU", "client_id": "C999"}))
    commandes.append(commandes[-10])  # double export d'une commande
    commandes.append(derniere.model_copy(update={"id": "CMD-FUTURE", "date": d.date_du_jour + timedelta(days=9)}))
    premiere_ligne = derniere.lignes[0]
    commandes.append(  # quantité saisie avec un zéro de trop
        derniere.model_copy(
            update={
                "id": "CMD-QUANTITE-ABERRANTE",
                "lignes": (premiere_ligne.model_copy(update={"quantite": premiere_ligne.quantite * 100}),),
            }
        )
    )

    lots = list(d.lots)
    lots[2] = lots[2].model_copy(update={"date_reception": lots[2].dlc + timedelta(days=5)})  # reçu après sa DLC
    lots.append(lots[10].model_copy(update={"id": "L-PERIME", "dlc": d.date_du_jour - timedelta(days=4)}))
    lots.append(lots[11].model_copy(update={"id": "L-ORPHELIN", "produit_code": "ZZ998"}))
    return DonneesSimulees(clients, produits, commandes, lots, d.date_du_jour)


# ---------------------------------------------------------------------------------
# Application
# ---------------------------------------------------------------------------------


def _page[T](
    elements: list[T], chemin: str, page: int, taille: int, filtres: dict[str, str]
) -> tuple[list[T], str | None]:
    """Découpe une liste en pages ; `next` reprend les filtres de la requête."""
    debut = (page - 1) * taille
    morceau = elements[debut : debut + taille]
    suivant = None
    if debut + taille < len(elements):
        suivant = f"{chemin}?{urlencode({**filtres, 'page': page + 1, 'taille': taille})}"
    return morceau, suivant


def creer_simulateur(
    source: DataSource | None = None,
    jeton: str = "jeton-de-demonstration",
    anomalies: bool = False,
    latence_ms: int = 0,
) -> FastAPI:
    donnees = charger_donnees(source or MockDataSource(), anomalies)
    app = FastAPI(
        title="Contrat d'interface du datahub (copilote télévente)",
        description=(
            "Ressources que le datahub doit exposer au copilote, EN LECTURE SEULE. "
            "Authentification : en-tête `Authorization: Bearer <jeton>`. "
            "Pagination : paramètres `page` (à partir de 1) et `taille`, réponse `{items, next}`. "
            "Erreurs : 401 si le jeton est absent ou invalide, 404 si la ressource n'existe pas."
        ),
        version="1.0",
    )

    async def authentifier(authorization: Annotated[str | None, Header()] = None) -> None:
        if latence_ms:
            await asyncio.sleep(latence_ms / 1000)
        attendu = f"Bearer {jeton}"
        if authorization is None or not hmac.compare_digest(authorization, attendu):
            raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Jeton invalide ou absent.")

    securite = [Depends(authentifier)]

    @app.get("/clients", response_model=PageClients, dependencies=securite, tags=["clients"])
    def clients(page: Page = 1, taille: Taille = TAILLE_PAGE_PAR_DEFAUT) -> PageClients:
        """Clients actifs, avec le télévendeur en charge (champ `commercial`)."""
        items, suivant = _page(donnees.clients, "/clients", page, taille, {})
        return PageClients(items=items, next=suivant)

    @app.get("/clients/{client_id}", response_model=Client, dependencies=securite, tags=["clients"])
    def client(client_id: str) -> Client:
        """Un client ; 404 s'il n'existe pas."""
        trouve = next((c for c in donnees.clients if c.id == client_id), None)
        if trouve is None:
            raise HTTPException(status.HTTP_404_NOT_FOUND, f"Client inconnu : {client_id}")
        return trouve

    @app.get("/commandes", response_model=PageCommandes, dependencies=securite, tags=["commandes"])
    def commandes(
        client_id: Annotated[str | None, Query(description="Restreint aux commandes de ce client")] = None,
        depuis: Annotated[dt.date | None, Query(description="Date de début incluse (AAAA-MM-JJ)")] = None,
        page: Page = 1,
        taille: Taille = TAILLE_PAGE_PAR_DEFAUT,
    ) -> PageCommandes:
        """Historique des commandes, lignes comprises (le copilote lit environ 6 mois)."""
        selection = [
            CommandeContrat(id=c.id, client_id=c.client_id, date=c.date, lignes=list(c.lignes))
            for c in donnees.commandes
            if (client_id is None or c.client_id == client_id) and (depuis is None or c.date >= depuis)
        ]
        filtres = {"client_id": client_id} if client_id else {}
        if depuis is not None:
            filtres["depuis"] = depuis.isoformat()
        items, suivant = _page(selection, "/commandes", page, taille, filtres)
        return PageCommandes(items=items, next=suivant)

    @app.get("/produits", response_model=PageProduits, dependencies=securite, tags=["catalogue"])
    def produits(page: Page = 1, taille: Taille = TAILLE_PAGE_PAR_DEFAUT) -> PageProduits:
        """Catalogue : prix tarif HT, famille (frais / surgelé) et durée de vie typique."""
        items, suivant = _page(donnees.produits, "/produits", page, taille, {})
        return PageProduits(items=items, next=suivant)

    @app.get("/stock/lots", response_model=PageLots, dependencies=securite, tags=["stock"])
    def lots(page: Page = 1, taille: Taille = TAILLE_PAGE_PAR_DEFAUT) -> PageLots:
        """Stock DISPONIBLE à la vente, par lot avec sa DLC (hors stock réservé ou bloqué)."""
        items, suivant = _page(donnees.lots, "/stock/lots", page, taille, {})
        return PageLots(items=items, next=suivant)

    return app


def main() -> None:
    import uvicorn

    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--hote", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=8100)
    parser.add_argument("--jeton", default=os.environ.get("DATAHUB_TOKEN", "jeton-de-demonstration"))
    parser.add_argument("--anomalies", action="store_true", help="injecter des défauts de données réalistes")
    parser.add_argument("--latence-ms", type=int, default=0, help="latence ajoutée à chaque requête")
    args = parser.parse_args()
    app = creer_simulateur(jeton=args.jeton, anomalies=args.anomalies, latence_ms=args.latence_ms)
    uvicorn.run(app, host=args.hote, port=args.port)


if __name__ == "__main__":
    main()
