"""Rendu texte de la fiche (copier-coller, impression, affichage brut)."""

from __future__ import annotations

from copilote.analyses import StatutManquant

from . import formatage as fmt
from .modeles import Fiche, ModeFiche

LIBELLES_MODE = {
    ModeFiche.IA: "Rédigée par IA",
    ModeFiche.IA_SIMULEE: "Rédaction IA simulée (rejeu)",
    ModeFiche.REPLI: "Rédigée sans IA (mode repli)",
}


def fiche_en_texte(fiche: Fiche) -> str:
    c, h = fiche.client, fiche.habitudes
    entete = f"Contact : {c.contact} — {c.telephone} | Date : {fmt.date_longue(fiche.date_du_jour)}"
    if h.prochain_jour_habituel:
        entete += f" | Prochaine commande habituelle : {fmt.jour_et_date(h.prochain_jour_habituel)}"
    lignes = [f"FICHE D'APPEL — {c.nom} ({c.type}, {c.ville})", entete, "", "HABITUDES", fiche.resume_habitudes]
    if h.panier_moyen_ht is not None:
        indicateurs = f"{h.nb_commandes} commandes sur 6 mois · panier moyen {fmt.euros(h.panier_moyen_ht)} HT"
        if h.tendance_ca_pct is not None:
            indicateurs += f" · tendance 3 mois {h.tendance_ca_pct:+d} %"
        lignes.append(indicateurs)

    if fiche.points_attention:
        lignes += ["", "POINTS D'ATTENTION", *(f"! {p}" for p in fiche.points_attention)]

    lignes += ["", "PRODUITS HABITUELS NON COMMANDÉS"]
    lignes += [
        f"- {m.libelle} (habituellement {fmt.quantite(m.quantite_habituelle, m.unite)})"
        f"{' [décroché]' if m.statut is StatutManquant.DECROCHE else ''} : {m.commentaire}"
        for m in fiche.produits_manquants
    ] or ["- Rien à signaler : le client est à jour de ses commandes habituelles."]

    lignes += ["", "STOCK À ÉCOULER"]
    lignes += [
        f"- {s.libelle} — lot {s.lot_id}, DLC {fmt.date_longue(s.dlc)} — {fmt.euros(s.prix_unitaire_ht)} → "
        f"{fmt.euros(s.prix_propose_ht)} HT (-{s.remise_pct} %) : {s.argument}"
        for s in fiche.stock_a_ecouler
    ] or ["- Aucun produit à écouler pertinent pour ce client."]

    if fiche.suggestions:
        lignes += ["", "À PROPOSER AUSSI"]
        lignes += [f"- {s.libelle} ({fmt.euros(s.prix_unitaire_ht)} HT) : {s.argument}" for s in fiche.suggestions]

    lignes += ["", "ACCROCHES", *(f"« {a} »" for a in fiche.accroches)]

    if fiche.panier.lignes:
        lignes += ["", f"PANIER PROPOSÉ ({fmt.euros(fiche.panier.total_ht)} HT)"]
        lignes += [
            f"- {fmt.quantite(l.quantite, l.unite)} {l.libelle} à {fmt.euros(l.prix_net_ht)}"
            + (f" (-{l.remise_pct} %)" if l.remise_pct else "")
            for l in fiche.panier.lignes
        ]

    mention = LIBELLES_MODE[fiche.mode] + (f" — {fiche.modele}" if fiche.modele else "")
    if fiche.avertissement:
        mention += f" — {fiche.avertissement}"
    lignes += ["", f"[{mention}]"]
    return "\n".join(lignes)
