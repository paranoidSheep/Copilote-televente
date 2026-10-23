"""Stock à écouler : lots à DLC courte ou produits en surstock, et leur pertinence par client."""

from __future__ import annotations

from datetime import date
from enum import IntEnum, StrEnum

from pydantic import Field

from copilote.domaine import Famille, Produit

from .apprentissage import AUCUN_APPRENTISSAGE, ModeleAcceptation, RetourClients
from .base import Resultat, memoise_par_referentiel
from .referentiel import Referentiel
from .regles import ReglesMetier


class MotifEcoulement(StrEnum):
    DLC_COURTE = "dlc_courte"
    SURSTOCK = "surstock"


class Pertinence(IntEnum):
    """Intérêt d'un produit pour un client donné (plus c'est haut, plus c'est pertinent)."""

    AUCUNE = 0
    CLIENTS_SIMILAIRES = 1  # acheté par d'autres établissements du même type
    DEJA_ACHETE = 2  # le client l'a déjà acheté
    HABITUEL = 3  # le client l'achète régulièrement


class SituationStock(Resultat):
    """Un produit à écouler, avec son lot prioritaire (DLC la plus proche)."""

    code: str
    libelle: str
    categorie: str
    famille: Famille
    unite: str
    motifs: list[MotifEcoulement]
    lot_id: str
    quantite_lot: float
    dlc: date
    jours_avant_dlc: int
    stock_total: float
    couverture_jours: float | None  # None : aucune vente récente
    prix_unitaire_ht: float
    remise_suggeree_pct: int
    prix_remise_ht: float

    @property
    def urgent(self) -> bool:
        return MotifEcoulement.DLC_COURTE in self.motifs


class PropositionStock(SituationStock):
    pertinence: Pertinence
    raison_pertinence: str
    retour_clients: RetourClients | None = Field(
        default=None, description="Acceptations et refus passés des établissements du même type"
    )


class StockAEcouler(Resultat):
    client_id: str
    date_du_jour: date
    regle_remise: str
    produits: list[PropositionStock]


# ---------------------------------------------------------------------------------
# Règles de DLC et de remise
# ---------------------------------------------------------------------------------


def seuil_dlc_courte(produit: Produit, regles: ReglesMetier) -> int:
    """Jours avant DLC en dessous desquels un lot est « à DLC courte ».

    Frais : une part de la durée de vie du produit, bornée (un poisson qui se
    garde 5 jours n'est pas « court » à J+4, un fromage l'est). Surgelé : fixe.
    """
    if produit.famille is Famille.SURGELE:
        return regles.dlc_courte_surgele_jours
    seuil = round(produit.duree_vie_jours * regles.part_duree_vie_dlc_courte)
    return max(regles.dlc_courte_frais_min_jours, min(regles.dlc_courte_frais_max_jours, seuil))


def remise_suggeree(
    famille: Famille,
    jours_avant_dlc: int,
    couverture_jours: float | None,
    dlc_courte: bool,
    regles: ReglesMetier,
) -> int:
    """Remise suggérée (%) selon l'urgence d'écoulement ; la plus forte des remises
    applicables est retenue, dans la limite du plafond.

    `couverture_jours = None` signifie « aucune vente récente » : stock dormant.
    """
    remise = 0
    if dlc_courte:
        if famille is Famille.FRAIS:
            remise = regles.remises_dlc_courte_frais.get(jours_avant_dlc, regles.remise_dlc_courte_frais_defaut)
        else:
            remise = (
                regles.remise_dlc_tres_courte_surgele if jours_avant_dlc <= 15 else regles.remise_dlc_courte_surgele
            )
    seuil = regles.seuil_surstock_jours[famille]
    if couverture_jours is None or couverture_jours > seuil:
        gros = couverture_jours is None or couverture_jours > 2 * seuil
        remise = max(remise, regles.remise_gros_surstock if gros else regles.remise_surstock)
    return min(remise, regles.remise_max_pct)


def description_regle_remise(regles: ReglesMetier) -> str:
    frais = ", ".join(f"{pct} % à J+{j}" for j, pct in sorted(regles.remises_dlc_courte_frais.items()))
    return (
        f"DLC courte frais : {frais}, {regles.remise_dlc_courte_frais_defaut} % au-delà. "
        f"Surgelé à DLC proche : {regles.remise_dlc_courte_surgele}-{regles.remise_dlc_tres_courte_surgele} %. "
        f"Surstock : {regles.remise_surstock}-{regles.remise_gros_surstock} %. "
        f"Plafond {regles.remise_max_pct} %. La remise suggérée est un maximum."
    )


# ---------------------------------------------------------------------------------
# Situations de stock (tous clients confondus)
# ---------------------------------------------------------------------------------


@memoise_par_referentiel
def situations_stock(ref: Referentiel) -> tuple[SituationStock, ...]:
    """Tous les produits en stock qui doivent être écoulés, triés par urgence."""
    regles = ref.regles
    lots_par_produit: dict[str, list[tuple[date, str, float]]] = {}
    for lot in ref.lots:
        # Un lot qui expire aujourd'hui ou avant ne peut plus être livré : exclu.
        if (lot.dlc - ref.date_du_jour).days >= 1 and lot.quantite > 0:
            lots_par_produit.setdefault(lot.produit_code, []).append((lot.dlc, lot.id, lot.quantite))

    situations: list[SituationStock] = []
    for code, lots in lots_par_produit.items():
        produit = ref.produits.get(code)
        if produit is None:
            continue
        lots.sort()
        dlc, lot_id, quantite_lot = lots[0]
        stock_total = sum(q for _, _, q in lots)
        par_jour = ref.ventes_journalieres.get(code, 0.0)
        couverture = round(stock_total / par_jour, 1) if par_jour > 0 else None
        jours_dlc = (dlc - ref.date_du_jour).days

        motifs: list[MotifEcoulement] = []
        dlc_courte = jours_dlc <= seuil_dlc_courte(produit, regles)
        if dlc_courte:
            motifs.append(MotifEcoulement.DLC_COURTE)
        if couverture is None or couverture > regles.seuil_surstock_jours[produit.famille]:
            motifs.append(MotifEcoulement.SURSTOCK)
        if not motifs:
            continue

        remise = remise_suggeree(produit.famille, jours_dlc, couverture, dlc_courte, regles)
        situations.append(
            SituationStock(
                code=code,
                libelle=produit.libelle,
                categorie=produit.categorie,
                famille=produit.famille,
                unite=produit.unite,
                motifs=motifs,
                lot_id=lot_id,
                quantite_lot=quantite_lot,
                dlc=dlc,
                jours_avant_dlc=jours_dlc,
                stock_total=stock_total,
                couverture_jours=couverture,
                prix_unitaire_ht=produit.prix_unitaire_ht,
                remise_suggeree_pct=remise,
                prix_remise_ht=round(produit.prix_unitaire_ht * (1 - remise / 100), 2),
            )
        )
    situations.sort(key=lambda s: (not s.urgent, s.jours_avant_dlc, s.code))
    return tuple(situations)


# ---------------------------------------------------------------------------------
# Pertinence pour un client
# ---------------------------------------------------------------------------------


def nb_clients_similaires_acheteurs(ref: Referentiel, client_id: str, code: str) -> int:
    """Nombre de clients du même type ayant acheté le produit au moins `achats_min_adoption` fois."""
    achats = ref.achats_par_produit_et_client.get(code, {})
    return sum(1 for c in ref.clients_similaires(client_id) if achats.get(c.id, 0) >= ref.regles.achats_min_adoption)


def evaluer_pertinence(ref: Referentiel, client_id: str, code: str) -> tuple[Pertinence, str]:
    """Pertinence d'un produit pour un client, avec une justification lisible."""
    if (habituel := ref.produits_recurrents(client_id).get(code)) is not None:
        return Pertinence.HABITUEL, f"produit acheté régulièrement ({habituel.nb_commandes} commandes sur 6 mois)"
    deja = ref.recurrences(client_id).get(code)
    if deja is not None:
        return Pertinence.DEJA_ACHETE, f"déjà acheté {deja.nb_commandes} fois sur 6 mois"
    similaires = ref.clients_similaires(client_id)
    n = nb_clients_similaires_acheteurs(ref, client_id, code)
    if similaires and n >= min(ref.regles.achats_min_adoption, len(similaires)):
        type_client = ref.client(client_id).type
        return Pertinence.CLIENTS_SIMILAIRES, f"acheté par {n} autre(s) client(s) de type « {type_client} »"
    return Pertinence.AUCUNE, "aucun lien avec les achats du client ou de clients similaires"


def analyser_stock_client(
    ref: Referentiel, client_id: str, limite: int = 6, acceptation: ModeleAcceptation = AUCUN_APPRENTISSAGE
) -> StockAEcouler:
    """Produits à écouler pertinents pour ce client, du plus au moins pertinent puis par urgence.

    Les retours des établissements du même type (`acceptation`) modulent la pertinence
    d'une demi-marche : un produit souvent accepté passe devant, un produit souvent refusé recule.
    """
    type_client = ref.client(client_id).type
    propositions: list[PropositionStock] = []
    for situation in situations_stock(ref):
        pertinence, raison = evaluer_pertinence(ref, client_id, situation.code)
        if pertinence is Pertinence.AUCUNE:
            continue
        propositions.append(
            PropositionStock(
                **situation.model_dump(),
                pertinence=pertinence,
                raison_pertinence=raison,
                retour_clients=acceptation.retour(situation.code, type_client),
            )
        )
    poids = ref.regles.apprentissage_poids_pertinence

    def rang(p: PropositionStock) -> tuple[float, bool, int, str]:
        modulation = poids * p.retour_clients.sens if p.retour_clients else 0.0
        return (-(p.pertinence + modulation), not p.urgent, p.jours_avant_dlc, p.code)

    propositions.sort(key=rang)
    return StockAEcouler(
        client_id=client_id,
        date_du_jour=ref.date_du_jour,
        regle_remise=description_regle_remise(ref.regles),
        produits=propositions[:limite],
    )
