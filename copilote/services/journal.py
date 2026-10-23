"""Enregistrement et exploitation des comptes-rendus d'appels."""

from __future__ import annotations

from collections.abc import Callable
from datetime import datetime, timedelta

from copilote.domaine import ErreurCopilote
from copilote.fiche import formatage as fmt
from copilote.horloge import Horloge
from copilote.journal import (
    CompteRendu,
    DepotJournal,
    NouveauCompteRendu,
    Reponse,
    StatistiquesAppels,
    calculer_statistiques,
)

from .referentiel import FournisseurReferentiel


class ErreurValidation(ErreurCopilote):
    """Donnée saisie incohérente avec le référentiel."""


class ServiceJournal:
    def __init__(
        self,
        depot: DepotJournal,
        referentiels: FournisseurReferentiel,
        horloge: Horloge,
        apres_enregistrement: Callable[[str], None] = lambda _client_id: None,
    ) -> None:
        self._depot = depot
        self._referentiels = referentiels
        self._horloge = horloge
        self._apres_enregistrement = apres_enregistrement

    def enregistrer(self, nouveau: NouveauCompteRendu) -> CompteRendu:
        ref = self._referentiels.obtenir()
        ref.client(nouveau.client_id)  # lève ClientIntrouvable
        inconnus = sorted({l.code for l in nouveau.lignes} - set(ref.produits))
        if inconnus:
            raise ErreurValidation(f"Produits inconnus : {', '.join(inconnus)}")
        compte_rendu = self._depot.enregistrer(nouveau, self._horloge.maintenant())
        self._apres_enregistrement(nouveau.client_id)  # ex. invalider la fiche en cache
        return compte_rendu

    def lister(
        self, client_id: str | None = None, jours: int | None = None, limite: int | None = None
    ) -> list[CompteRendu]:
        depuis = self._depuis(jours)
        return self._depot.lister(client_id=client_id, depuis=depuis, limite=limite)

    def obtenir(self, compte_rendu_id: int) -> CompteRendu | None:
        return self._depot.obtenir(compte_rendu_id)

    def statistiques(self, jours: int = 30) -> StatistiquesAppels:
        return calculer_statistiques(self._depot.lister(depuis=self._depuis(jours)))

    def texte_saisie_erp(self, compte_rendu: CompteRendu) -> str:
        """Récapitulatif des produits acceptés, à saisir dans l'ERP par le télévendeur."""
        client = self._referentiels.obtenir().client(compte_rendu.client_id)
        acceptees = [l for l in compte_rendu.lignes if l.reponse is Reponse.ACCEPTE]
        lignes = [
            f"COMMANDE À SAISIR — {client.nom} ({client.id})",
            f"Appel du {compte_rendu.cree_le:%d/%m/%Y à %H:%M} par {compte_rendu.televendeur}",
            "",
        ]
        lignes += [
            f"{l.code}  {fmt.quantite(l.quantite, l.unite):<12}  {l.libelle}  @ "
            + (
                f"{fmt.euros(l.prix_net_ht)} ({fmt.euros(l.prix_unitaire_ht)} -{l.remise_pct} %)"
                if l.remise_pct
                else fmt.euros(l.prix_unitaire_ht)
            )
            for l in acceptees
        ] or ["(aucun produit accepté)"]
        lignes += ["", f"Total HT estimé : {fmt.euros(compte_rendu.montant_accepte_ht)}"]
        if compte_rendu.notes:
            lignes += [f"Notes : {compte_rendu.notes}"]
        return "\n".join(lignes)

    def _depuis(self, jours: int | None) -> datetime | None:
        if jours is None:
            return None
        debut = self._horloge.maintenant() - timedelta(days=jours)
        return debut.replace(hour=0, minute=0, second=0)
