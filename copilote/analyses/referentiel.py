"""Instantané indexé des données utilisées par les analyses.

Le `Referentiel` est chargé une fois depuis la `DataSource`, puis toutes les
analyses travaillent dessus sans aucun accès réseau : elles sont pures,
rapides et faciles à tester. Les index (commandes par client, ventes récentes
par produit…) sont calculés à la demande puis mémorisés.

Au chargement, les données inexploitables (références orphelines, doublons,
lots périmés…) sont écartées : les analyses ne voient que des données cohérentes.
"""

from __future__ import annotations

from collections import defaultdict
from collections.abc import Mapping
from dataclasses import dataclass
from datetime import date, timedelta
from functools import cached_property

from copilote.datahub import DataSource
from copilote.domaine import Client, ClientIntrouvable, Commande, Lot, Produit, ProduitIntrouvable

from .exploitabilite import Ecart, filtrer_exploitables
from .regles import REGLES_PAR_DEFAUT, ReglesMetier
from .statistiques import Recurrence, produits_recurrents, recurrences


@dataclass(frozen=True, eq=False)  # eq=False : identité = instantané (sert de clé de cache)
class Referentiel:
    date_du_jour: date
    clients: Mapping[str, Client]
    produits: Mapping[str, Produit]
    commandes: tuple[Commande, ...]  # période analysée, tous clients, triées par date
    lots: tuple[Lot, ...]
    regles: ReglesMetier = REGLES_PAR_DEFAUT
    ecarts: tuple[Ecart, ...] = ()  # enregistrements écartés au chargement (voir `exploitabilite`)

    @classmethod
    def charger(cls, source: DataSource, regles: ReglesMetier = REGLES_PAR_DEFAUT) -> Referentiel:
        aujourd_hui = source.date_du_jour()
        debut = aujourd_hui - timedelta(days=regles.periode_analyse_jours)
        donnees = filtrer_exploitables(
            aujourd_hui,
            clients=source.get_clients(),
            produits=source.get_products(),
            commandes=source.get_order_history(depuis=debut),
            lots=source.get_stock(),
        )
        return cls(
            date_du_jour=aujourd_hui,
            clients=donnees.clients,
            produits=donnees.produits,
            commandes=donnees.commandes,
            lots=donnees.lots,
            regles=regles,
            ecarts=donnees.ecarts,
        )

    # -- Accès unitaires ------------------------------------------------------------

    def client(self, client_id: str) -> Client:
        try:
            return self.clients[client_id]
        except KeyError:
            raise ClientIntrouvable(client_id) from None

    def produit(self, code: str) -> Produit:
        try:
            return self.produits[code]
        except KeyError:
            raise ProduitIntrouvable(code) from None

    def commandes_client(self, client_id: str) -> tuple[Commande, ...]:
        self.client(client_id)  # lève ClientIntrouvable
        return self._commandes_par_client.get(client_id, ())

    def clients_similaires(self, client_id: str) -> tuple[Client, ...]:
        """Clients du même type d'établissement (hors le client lui-même)."""
        type_client = self.client(client_id).type
        return tuple(c for c in self._clients_par_type.get(type_client, ()) if c.id != client_id)

    def recurrences(self, client_id: str) -> Mapping[str, Recurrence]:
        """Récurrence d'achat de chaque produit déjà acheté par le client (mémorisé)."""
        if client_id not in self._cache_recurrences:
            self._cache_recurrences[client_id] = recurrences(self.commandes_client(client_id))
        return self._cache_recurrences[client_id]

    def produits_recurrents(self, client_id: str) -> Mapping[str, Recurrence]:
        """Produits « habituels » du client au sens des règles métier (mémorisé)."""
        if client_id not in self._cache_recurrents:
            self._cache_recurrents[client_id] = produits_recurrents(self.commandes_client(client_id), self.regles)
        return self._cache_recurrents[client_id]

    # -- Index mémorisés ------------------------------------------------------------

    @cached_property
    def _cache_recurrences(self) -> dict[str, Mapping[str, Recurrence]]:
        return {}

    @cached_property
    def _cache_recurrents(self) -> dict[str, Mapping[str, Recurrence]]:
        return {}

    @cached_property
    def _commandes_par_client(self) -> Mapping[str, tuple[Commande, ...]]:
        index: dict[str, list[Commande]] = defaultdict(list)
        for commande in self.commandes:
            index[commande.client_id].append(commande)
        return {k: tuple(v) for k, v in index.items()}

    @cached_property
    def _clients_par_type(self) -> Mapping[str, tuple[Client, ...]]:
        index: dict[str, list[Client]] = defaultdict(list)
        for client in self.clients.values():
            index[client.type].append(client)
        return {k: tuple(v) for k, v in index.items()}

    @cached_property
    def ventes_journalieres(self) -> Mapping[str, float]:
        """Quantité moyenne vendue par jour et par produit, sur la fenêtre de rotation."""
        fenetre = self.regles.fenetre_rotation_jours
        limite = self.date_du_jour - timedelta(days=fenetre)
        ventes: dict[str, float] = defaultdict(float)
        for commande in self.commandes:
            if commande.date >= limite:
                for ligne in commande.lignes:
                    ventes[ligne.produit_code] += ligne.quantite
        return {code: total / fenetre for code, total in ventes.items()}

    @cached_property
    def achats_par_produit_et_client(self) -> Mapping[str, Mapping[str, int]]:
        """Pour chaque produit, nombre de commandes le contenant, par client."""
        index: dict[str, dict[str, int]] = defaultdict(lambda: defaultdict(int))
        for commande in self.commandes:
            for code in commande.codes_produits:
                index[code][commande.client_id] += 1
        return {code: dict(par_client) for code, par_client in index.items()}
