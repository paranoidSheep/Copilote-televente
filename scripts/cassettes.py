"""Outillage des cassettes de l'IA simulée.

    python -m scripts.cassettes apercu C001 C002   # ce que les outils renvoient (pour rédiger)
    python -m scripts.cassettes verifier           # contrôle toutes les cassettes

Une cassette est valide si sa rédaction respecte le schéma `Redaction`, ne cite
que des produits présents dans les résultats des outils, ne dépasse aucune
remise suggérée et propose 2 ou 3 accroches. La vérification est aussi
exécutée par les tests.
"""

from __future__ import annotations

import argparse
import sys
from dataclasses import dataclass

from pydantic import ValidationError

from copilote.agent.llm import DOSSIER_CASSETTES, Cassette
from copilote.analyses import ContexteClient, Referentiel, construire_contexte
from copilote.config import Config
from copilote.datahub import creer_source
from copilote.fiche import Redaction
from copilote.fiche import formatage as fmt


@dataclass(frozen=True)
class Anomalie:
    client_id: str
    message: str


def apercu(contexte: ContexteClient) -> str:
    """Résumé compact des résultats d'outils d'un client."""
    h = contexte.habitudes
    c = h.client
    lignes = [
        f"=== {c.id} {c.nom} — {c.type}, {c.ville} — contact {c.contact}",
        f"{h.nb_commandes} cmd, {h.commandes_par_semaine}/sem, jours {[str(j) for j in h.jours_habituels]}, "
        f"prochain {h.prochain_jour_habituel}, panier {h.panier_moyen_ht} €, tendance {h.tendance_ca_pct} %, "
        f"dernière il y a {h.jours_depuis_derniere_commande} j (intervalle {h.intervalle_median_jours})",
        "Récurrents : "
        + "; ".join(f"{p.code} {p.libelle} {p.frequence_pct}% q{fmt.nombre(p.quantite_habituelle)}" for p in h.produits_recurrents),
        "Catégories : " + ", ".join(f"{p.categorie} {p.part_pct}%" for p in h.repartition_categories[:5]),
        "MANQUANTS :",
        *(
            f"  {m.code} {m.libelle} [{m.statut}] rythme {m.rythme_habituel_jours} j, depuis {m.jours_depuis_derniere_commande} j, "
            f"q{fmt.nombre(m.quantite_habituelle)} {m.unite}, freq {m.frequence_pct}%"
            for m in contexte.manquants.produits
        ),
        "STOCK :",
        *(
            f"  {s.code} {s.libelle} {[str(m) for m in s.motifs]} DLC J+{s.jours_avant_dlc} ({s.dlc}), "
            f"lot {fmt.nombre(s.quantite_lot)} {s.unite}, {s.prix_unitaire_ht} € remise max {s.remise_suggeree_pct}% "
            f"-> pertinence {s.pertinence.name} ({s.raison_pertinence})"
            for s in contexte.stock.produits
        ),
        "SUGGESTIONS :",
        *(
            f"  {s.code} {s.libelle} {s.taux_adoption_pct}% ({s.nb_clients_similaires_acheteurs} clients), "
            f"{s.prix_unitaire_ht} €, à écouler={s.en_stock_a_ecouler}"
            for s in contexte.suggestions.produits
        ),
    ]
    return "\n".join(lignes)


def verifier_cassette(cassette: Cassette, contexte: ContexteClient) -> list[Anomalie]:
    anomalies: list[Anomalie] = []

    def signaler(message: str) -> None:
        anomalies.append(Anomalie(cassette.client_id, message))

    if cassette.date_reference != contexte.habitudes.date_du_jour:
        signaler(f"date de référence {cassette.date_reference} ≠ {contexte.habitudes.date_du_jour}")
    try:
        redaction = Redaction.model_validate(cassette.redaction)
    except ValidationError as exc:
        signaler(f"rédaction invalide : {exc.error_count()} erreur(s)")
        return anomalies

    manquants = {p.code for p in contexte.manquants.produits}
    stock = {p.code: p for p in contexte.stock.produits}
    suggestions = {p.code for p in contexte.suggestions.produits}
    for m in redaction.produits_manquants:
        if m.code not in manquants:
            signaler(f"produit manquant inconnu : {m.code}")
    for s in redaction.stock_a_ecouler:
        if s.code not in stock:
            signaler(f"produit de stock inconnu : {s.code}")
        elif s.remise_pct > stock[s.code].remise_suggeree_pct:
            signaler(f"remise trop forte sur {s.code} : {s.remise_pct} > {stock[s.code].remise_suggeree_pct}")
    for g in redaction.suggestions:
        if g.code not in suggestions:
            signaler(f"suggestion inconnue : {g.code}")
    if not 2 <= len(redaction.accroches) <= 3:
        signaler(f"{len(redaction.accroches)} accroche(s) au lieu de 2 ou 3")
    if contexte.habitudes.client.contact.split()[-1] not in " ".join(redaction.accroches):
        signaler("aucune accroche ne cite le contact")
    return anomalies


def verifier_toutes(ref: Referentiel) -> list[Anomalie]:
    anomalies: list[Anomalie] = []
    for client_id in sorted(ref.clients):
        chemin = DOSSIER_CASSETTES / f"{client_id}.json"
        if not chemin.exists():
            anomalies.append(Anomalie(client_id, "cassette absente"))
            continue
        cassette = Cassette.model_validate_json(chemin.read_text(encoding="utf-8"))
        anomalies += verifier_cassette(cassette, construire_contexte(ref, client_id, []))
    return anomalies


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sous = parser.add_subparsers(dest="commande", required=True)
    p_apercu = sous.add_parser("apercu")
    p_apercu.add_argument("clients", nargs="*")
    sous.add_parser("verifier")
    args = parser.parse_args()

    ref = Referentiel.charger(creer_source(Config()))
    if args.commande == "apercu":
        for client_id in args.clients or sorted(ref.clients):
            print(apercu(construire_contexte(ref, client_id, [])), end="\n\n")
        return 0

    anomalies = verifier_toutes(ref)
    for a in anomalies:
        print(f"{a.client_id} : {a.message}")
    print(f"{len(ref.clients) - len({a.client_id for a in anomalies})}/{len(ref.clients)} cassettes valides")
    return 1 if anomalies else 0


if __name__ == "__main__":
    sys.exit(main())
