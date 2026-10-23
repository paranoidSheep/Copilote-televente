"""Peuple le journal d'appels avec des comptes-rendus FICTIFS (démonstration).

    python -m scripts.peupler_journal_demo            # ajoute ~2 semaines d'appels
    python -m scripts.peupler_journal_demo --vider    # repart d'un journal vide

Les appels sont générés de façon déterministe à partir des propositions des
fiches (produits manquants, stock, suggestions), avec des taux d'acceptation
réalistes. Quelques clients demandent à être rappelés aujourd'hui, et certains
produits sont refusés : de quoi illustrer la file d'appels, les statistiques et
les garde-fous (produits refusés non reproposés).
"""

from __future__ import annotations

import argparse
import random
from datetime import datetime, time, timedelta

from copilote.analyses import Referentiel, construire_contexte
from copilote.config import Config
from copilote.datahub import creer_source
from copilote.journal import DepotSQLite, Issue, LigneCompteRendu, NouveauCompteRendu, Origine, Reponse

GRAINE = 7
JOURS = 14
TAUX_ACCEPTATION = {Origine.MANQUANT: 0.65, Origine.STOCK: 0.45, Origine.SUGGESTION: 0.25}
NOTES = {
    Issue.COMMANDE: ["Commande passée sans difficulté.", "Client satisfait des remises.", ""],
    Issue.PAS_DE_BESOIN: ["Stock suffisant cette semaine.", "Fermeture exceptionnelle prévue.", ""],
    Issue.RAPPELER: ["Le chef est absent, rappeler.", "Attend le planning des menus."],
    Issue.INJOIGNABLE: ["Messagerie.", "Ligne occupée."],
}


RAPPELS_DU_JOUR = [
    ("C012", "La gestionnaire valide les menus de novembre jeudi soir : rappeler vendredi matin."),
    ("C026", "Mme Lemoine attend la confirmation d'un mariage de 120 couverts."),
]


def _lignes(rng: random.Random, ref: Referentiel, client_id: str) -> list[LigneCompteRendu]:
    contexte = construire_contexte(ref, client_id, [])
    propositions: list[tuple[Origine, str, float, int]] = [
        *((Origine.MANQUANT, m.code, m.quantite_habituelle, 0) for m in contexte.manquants.produits[:3]),
        *((Origine.STOCK, s.code, 2.0, s.remise_suggeree_pct) for s in contexte.stock.produits[:3]),
        *((Origine.SUGGESTION, g.code, 1.0, 0) for g in contexte.suggestions.produits[:2]),
    ]
    lignes = []
    vus: set[str] = set()
    for origine, code, quantite, remise in propositions:
        if code in vus:  # un produit à la fois manquant et à écouler n'est proposé qu'une fois
            continue
        vus.add(code)
        produit = ref.produit(code)
        tirage = rng.random()
        reponse = (
            Reponse.ACCEPTE
            if tirage < TAUX_ACCEPTATION[origine]
            else Reponse.REFUSE
            if tirage < 0.9
            else Reponse.SANS_REPONSE
        )
        lignes.append(
            LigneCompteRendu(
                code=code,
                libelle=produit.libelle,
                unite=produit.unite,
                origine=origine,
                reponse=reponse,
                quantite=quantite if reponse is Reponse.ACCEPTE else 0,
                prix_unitaire_ht=produit.prix_unitaire_ht,
                remise_pct=remise,
            )
        )
    return lignes


def peupler(depot: DepotSQLite, ref: Referentiel, graine: int = GRAINE) -> int:
    rng = random.Random(graine)
    clients = sorted(ref.clients.values(), key=lambda c: c.id)
    nombre = 0
    for decalage in range(JOURS, 0, -1):
        jour = ref.date_du_jour - timedelta(days=decalage)
        if jour.weekday() == 6:  # pas d'appels le dimanche
            continue
        for client in rng.sample(clients, rng.randint(2, 5)):
            issue = rng.choices(list(Issue), weights=[6, 2, 1, 1])[0]
            lignes = _lignes(rng, ref, client.id) if issue is Issue.COMMANDE else []
            if issue is Issue.COMMANDE and not any(l.reponse is Reponse.ACCEPTE for l in lignes):
                issue, lignes = Issue.PAS_DE_BESOIN, []
            rappel = ref.date_du_jour + timedelta(days=rng.randint(1, 3)) if issue is Issue.RAPPELER else None
            depot.enregistrer(
                NouveauCompteRendu(
                    client_id=client.id,
                    televendeur=client.commercial,
                    issue=issue,
                    notes=rng.choice(NOTES[issue]),
                    rappel_le=rappel,
                    mode_fiche="ia_simulee",
                    lignes=lignes,
                ),
                datetime.combine(jour, time(rng.randint(8, 11), rng.randint(0, 59))),
            )
            nombre += 1

    # Deux clients ont demandé hier à être rappelés aujourd'hui : ils remontent en tête de file.
    hier = datetime.combine(ref.date_du_jour - timedelta(days=1), time(16, 30))
    for client_id, note in RAPPELS_DU_JOUR:
        client = ref.client(client_id)
        depot.enregistrer(
            NouveauCompteRendu(
                client_id=client_id,
                televendeur=client.commercial,
                issue=Issue.RAPPELER,
                notes=note,
                rappel_le=ref.date_du_jour,
                mode_fiche="ia_simulee",
            ),
            hier,
        )
        nombre += 1
    return nombre


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--vider", action="store_true", help="supprimer le journal existant avant de le peupler")
    args = parser.parse_args()
    config = Config.depuis_environnement()
    if args.vider and config.chemin_journal.exists():
        config.chemin_journal.unlink()
    ref = Referentiel.charger(creer_source(config))
    nombre = peupler(DepotSQLite(config.chemin_journal), ref)
    print(f"{nombre} comptes-rendus fictifs ajoutés dans {config.chemin_journal}")


if __name__ == "__main__":
    main()
