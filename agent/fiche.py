"""Structure de la fiche d'appel, assemblage, mode repli et rendu texte.

Principe de sécurité : la fiche finale est TOUJOURS assemblée ici, à partir des
résultats des outils métier. La rédaction (par Claude ou par le mode repli) ne
fournit que des textes et une sélection de codes produits :
- un code produit absent des résultats des outils est ignoré (pas d'invention) ;
- une remise supérieure à la remise suggérée par l'outil est ramenée à ce maximum ;
- prix, DLC, quantités et indicateurs viennent exclusivement des outils.
"""

from __future__ import annotations

from datetime import date, datetime
from typing import Any, Literal

from pydantic import BaseModel, Field

from datahub.base import Client

# ---------------------------------------------------------------------------
# Rédaction : ce que produit l'IA (ou le mode repli)
# ---------------------------------------------------------------------------


class RedactionManquant(BaseModel):
    code: str
    commentaire: str


class RedactionStock(BaseModel):
    code: str
    remise_pct: int
    argument: str


class RedactionSuggestion(BaseModel):
    code: str
    argument: str


class Redaction(BaseModel):
    resume_habitudes: str
    produits_manquants: list[RedactionManquant] = Field(default_factory=list)
    stock_a_ecouler: list[RedactionStock] = Field(default_factory=list)
    suggestions: list[RedactionSuggestion] = Field(default_factory=list)
    accroches: list[str] = Field(default_factory=list)
    points_attention: list[str] = Field(default_factory=list)


# ---------------------------------------------------------------------------
# Fiche d'appel finale (renvoyée par l'API)
# ---------------------------------------------------------------------------


class ProduitRecurrent(BaseModel):
    code: str
    libelle: str
    unite: str
    frequence_pct: int
    quantite_habituelle: float


class Habitudes(BaseModel):
    resume: str
    nb_commandes: int
    commandes_par_semaine: float | None = None
    jours_habituels: list[str] = Field(default_factory=list)
    prochain_jour_habituel: str | None = None
    panier_moyen_ht: float | None = None
    ca_total_ht: float | None = None
    tendance_ca_pct: int | None = None
    derniere_commande: date | None = None
    jours_depuis_derniere_commande: int | None = None
    produits_recurrents: list[ProduitRecurrent] = Field(default_factory=list)


class ProduitManquant(BaseModel):
    code: str
    libelle: str
    unite: str
    quantite_habituelle: float
    rythme_habituel_jours: float
    derniere_commande: date
    jours_depuis_derniere_commande: int
    statut: str
    commentaire: str


class ProduitAEcouler(BaseModel):
    code: str
    libelle: str
    unite: str
    motifs: list[str]
    lot_id: str
    quantite_lot: float
    dlc: date
    jours_avant_dlc: int
    prix_unitaire_ht: float
    remise_pct: int
    prix_remise_ht: float
    argument: str


class Suggestion(BaseModel):
    code: str
    libelle: str
    unite: str
    prix_unitaire_ht: float
    taux_adoption_pct: int
    argument: str


class Fiche(BaseModel):
    client: Client
    date_du_jour: date
    genere_le: datetime
    mode: Literal["ia", "repli"] = Field(description="« ia » : rédigée par Claude ; « repli » : rédigée sans LLM")
    modele: str | None = None
    avertissement: str | None = None
    habitudes: Habitudes
    produits_manquants: list[ProduitManquant]
    stock_a_ecouler: list[ProduitAEcouler]
    suggestions: list[Suggestion]
    accroches: list[str]
    points_attention: list[str]
    texte: str = ""


# ---------------------------------------------------------------------------
# Assemblage : rédaction + données des outils -> fiche
# ---------------------------------------------------------------------------

MAX_MANQUANTS = 5
MAX_STOCK = 4
MAX_SUGGESTIONS = 3
MAX_ACCROCHES = 3


def assembler_fiche(
    contexte: dict[str, Any],
    redaction: Redaction,
    mode: Literal["ia", "repli"],
    modele: str | None = None,
    avertissement: str | None = None,
) -> Fiche:
    """Construit la fiche finale en ne gardant que des données vérifiées par les outils."""
    hist = contexte["historique_client"]
    manquants_ref = {p["code"]: p for p in contexte["produits_habituels_manquants"]["produits"]}
    stock_ref = {p["code"]: p for p in contexte["stock_a_ecouler"]["produits"]}
    suggestions_ref = {p["code"]: p for p in contexte["suggestions_croisees"]["produits"]}

    habitudes = Habitudes(
        resume=redaction.resume_habitudes.strip(),
        nb_commandes=hist["nb_commandes"],
        commandes_par_semaine=hist.get("commandes_par_semaine"),
        jours_habituels=hist.get("jours_habituels", []),
        prochain_jour_habituel=hist.get("prochain_jour_habituel"),
        panier_moyen_ht=hist.get("panier_moyen_ht"),
        ca_total_ht=hist.get("ca_total_ht"),
        tendance_ca_pct=hist.get("tendance_ca_pct"),
        derniere_commande=hist.get("derniere_commande"),
        jours_depuis_derniere_commande=hist.get("jours_depuis_derniere_commande"),
        produits_recurrents=[ProduitRecurrent(**p) for p in hist.get("produits_recurrents", [])[:8]],
    )

    manquants = []
    for r in _sans_doublon(redaction.produits_manquants)[:MAX_MANQUANTS]:
        if (ref := manquants_ref.get(r.code)) is None:
            continue  # code inventé ou hors liste : ignoré
        manquants.append(ProduitManquant(**_depuis(ref, ProduitManquant, commentaire=r.commentaire.strip())))

    stock = []
    for r in _sans_doublon(redaction.stock_a_ecouler)[:MAX_STOCK]:
        if (ref := stock_ref.get(r.code)) is None:
            continue
        remise = max(0, min(r.remise_pct, ref["remise_suggeree_pct"]))  # jamais au-delà de la règle
        stock.append(
            ProduitAEcouler(
                **_depuis(
                    ref,
                    ProduitAEcouler,
                    remise_pct=remise,
                    prix_remise_ht=round(ref["prix_unitaire_ht"] * (1 - remise / 100), 2),
                    argument=r.argument.strip(),
                )
            )
        )

    suggestions = []
    for r in _sans_doublon(redaction.suggestions)[:MAX_SUGGESTIONS]:
        if (ref := suggestions_ref.get(r.code)) is None:
            continue
        suggestions.append(
            Suggestion(**_depuis(ref, Suggestion, argument=r.argument.strip()))
        )

    accroches = [a.strip() for a in redaction.accroches if a.strip()][:MAX_ACCROCHES]
    if len(accroches) < 2:  # garantit toujours au moins 2 accroches
        complements = _accroches_repli(contexte, manquants, stock, suggestions)
        accroches += [a for a in complements if a not in accroches][: 2 - len(accroches)]

    fiche = Fiche(
        client=hist["client"],
        date_du_jour=hist["date_du_jour"],
        genere_le=datetime.now().replace(microsecond=0),
        mode=mode,
        modele=modele,
        avertissement=avertissement,
        habitudes=habitudes,
        produits_manquants=manquants,
        stock_a_ecouler=stock,
        suggestions=suggestions,
        accroches=accroches,
        points_attention=[p.strip() for p in redaction.points_attention if p.strip()][:4],
    )
    fiche.texte = fiche_en_texte(fiche)
    return fiche


def _depuis(ref: dict[str, Any], modele: type[BaseModel], **valeurs: Any) -> dict[str, Any]:
    """Champs du modèle repris des données de l'outil, complétés/écrasés par `valeurs`."""
    return {**{k: ref[k] for k in modele.model_fields if k in ref}, **valeurs}


def _sans_doublon(elements: list) -> list:
    vus, resultat = set(), []
    for e in elements:
        if e.code not in vus:
            vus.add(e.code)
            resultat.append(e)
    return resultat


# ---------------------------------------------------------------------------
# Mode repli : rédaction par gabarits, sans LLM
# ---------------------------------------------------------------------------


def redaction_repli(contexte: dict[str, Any]) -> Redaction:
    """Rédige la fiche à partir des seuls résultats des outils (aucun appel à une IA)."""
    hist = contexte["historique_client"]
    manquants = contexte["produits_habituels_manquants"]["produits"][:MAX_MANQUANTS]
    stock = contexte["stock_a_ecouler"]["produits"][:MAX_STOCK]
    suggestions = contexte["suggestions_croisees"]["produits"][:MAX_SUGGESTIONS]
    type_client = hist["client"]["type"]

    return Redaction(
        resume_habitudes=_resume_repli(hist),
        produits_manquants=[
            RedactionManquant(
                code=m["code"],
                commentaire=(
                    f"Commandé d'habitude tous les {_jours(m['rythme_habituel_jours'])}, "
                    f"plus rien depuis {m['jours_depuis_derniere_commande']} jours."
                    + (" Possible achat chez un concurrent : à questionner." if m["statut"] == "décroché" else "")
                ),
            )
            for m in manquants
        ],
        stock_a_ecouler=[
            RedactionStock(code=s["code"], remise_pct=s["remise_suggeree_pct"], argument=_argument_stock(s))
            for s in stock
        ],
        suggestions=[
            RedactionSuggestion(
                code=s["code"],
                argument=(
                    f"Acheté régulièrement par {_clients(s['nb_clients_similaires_acheteurs'])} de type "
                    f"« {type_client} » ({s['taux_adoption_pct']} % d'entre eux), jamais commandé par ce client."
                ),
            )
            for s in suggestions
        ],
        accroches=_accroches_repli(contexte, manquants, stock, suggestions),
        points_attention=_points_attention_repli(hist, manquants),
    )


def _resume_repli(hist: dict[str, Any]) -> str:
    if not hist["nb_commandes"]:
        return "Aucune commande sur les 6 derniers mois : client à réactiver."
    jours = _liste_fr(hist["jours_habituels"]) or "sans jour fixe"
    phrases = [
        f"{hist['client']['type']} qui commande en moyenne {_nombre(hist['commandes_par_semaine'])} fois par semaine "
        f"({jours}), pour un panier moyen de {_euros(hist['panier_moyen_ht'])} HT."
    ]
    recurrents = [p["libelle"] for p in hist["produits_recurrents"][:3]]
    if recurrents:
        phrases.append(f"Produits phares : {_liste_fr(recurrents)}.")
    tendance = hist.get("tendance_ca_pct")
    if tendance is not None:
        if tendance >= 5:
            phrases.append(f"Activité en hausse ({tendance:+d} % sur 3 mois).")
        elif tendance <= -5:
            phrases.append(f"Activité en baisse ({tendance:+d} % sur 3 mois).")
        else:
            phrases.append("Activité stable sur 3 mois.")
    return " ".join(phrases)


def _argument_stock(s: dict[str, Any]) -> str:
    if "DLC courte" in s["motifs"]:
        return f"Lot à DLC du {_date_fr(s['dlc'])} (J+{s['jours_avant_dlc']}) : à proposer pour une utilisation rapide."
    return "Stock important sur ce produit : remise pour accélérer l'écoulement."


def _accroches_repli(
    contexte: dict[str, Any], manquants: list, stock: list, suggestions: list
) -> list[str]:
    """2 ou 3 phrases d'accroche à partir des éléments les plus forts de la fiche."""
    hist = contexte["historique_client"]
    contact = hist["client"]["contact"] or "Bonjour"
    prochain = hist.get("prochain_jour_habituel")
    accroches = []

    def champ(obj: Any, nom: str) -> Any:
        return obj[nom] if isinstance(obj, dict) else getattr(obj, nom)

    if manquants:
        m = manquants[0]
        accroches.append(
            f"Bonjour {contact}, je prépare votre commande"
            + (f" pour {prochain}" if prochain else "")
            + f" : je ne vois pas de {_minuscule(champ(m, 'libelle'))} depuis quelque temps, "
            f"je vous en remets {_quantite(champ(m, 'quantite_habituelle'), champ(m, 'unite'))} comme d'habitude ?"
        )
    if stock:
        s = stock[0]
        remise = champ(s, "remise_pct") if not isinstance(s, dict) else s["remise_suggeree_pct"]
        accroches.append(
            f"J'ai une belle opportunité cette semaine sur {_minuscule(champ(s, 'libelle'))} : "
            f"{remise} % de remise, soit {_euros(champ(s, 'prix_unitaire_ht') * (1 - remise / 100))} HT "
            f"le {champ(s, 'unite')}. Je vous en réserve ?"
        )
    if suggestions:
        g = suggestions[0]
        accroches.append(
            f"D'autres établissements comme le vôtre ont adopté {_minuscule(champ(g, 'libelle'))} ; "
            "voulez-vous que je vous en glisse un pour essayer ?"
        )
    if len(accroches) < 2:
        accroches.append(
            f"Bonjour {contact}, c'est votre télévendeur : avez-vous besoin de compléter votre commande"
            + (f" pour {prochain}" if prochain else "")
            + " ?"
        )
    if len(accroches) < 2:
        accroches.append("Avez-vous des besoins particuliers cette semaine : événement, nouveau plat à la carte ?")
    return accroches[:MAX_ACCROCHES]


def _points_attention_repli(hist: dict[str, Any], manquants: list[dict]) -> list[str]:
    points = []
    decroches = [m["libelle"] for m in manquants if m["statut"] == "décroché"]
    if decroches:
        points.append(f"Produits décrochés (probable concurrent) : {_liste_fr(decroches)}.")
    tendance = hist.get("tendance_ca_pct")
    if tendance is not None and tendance <= -10:
        points.append(f"Chiffre d'affaires en baisse de {abs(tendance)} % sur les 3 derniers mois.")
    attente = hist.get("jours_depuis_derniere_commande")
    intervalle = hist.get("intervalle_median_jours")
    if attente is not None and intervalle and attente > max(7, 2 * intervalle):
        points.append(f"Aucune commande depuis {attente} jours, contre une tous les {_jours(intervalle)} d'habitude.")
    return points


# ---------------------------------------------------------------------------
# Rendu texte (pour copier-coller, impression, ou affichage brut)
# ---------------------------------------------------------------------------


def fiche_en_texte(fiche: Fiche) -> str:
    c, h = fiche.client, fiche.habitudes
    lignes = [
        f"FICHE D'APPEL — {c.nom} ({c.type}, {c.ville})",
        f"Contact : {c.contact} — {c.telephone} | Date : {_date_fr(fiche.date_du_jour)}"
        + (f" | Prochaine commande habituelle : {h.prochain_jour_habituel}" if h.prochain_jour_habituel else ""),
        "",
        "HABITUDES",
        h.resume,
    ]
    if h.panier_moyen_ht is not None:
        lignes.append(
            f"{h.nb_commandes} commandes sur 6 mois · panier moyen {_euros(h.panier_moyen_ht)} HT"
            + (f" · tendance 3 mois {h.tendance_ca_pct:+d} %" if h.tendance_ca_pct is not None else "")
        )
    if fiche.points_attention:
        lignes += ["", "POINTS D'ATTENTION"] + [f"! {p}" for p in fiche.points_attention]
    lignes += ["", "PRODUITS HABITUELS NON COMMANDÉS"]
    lignes += [
        f"- {m.libelle} (habituellement {_quantite(m.quantite_habituelle, m.unite)}) : {m.commentaire}"
        for m in fiche.produits_manquants
    ] or ["- Rien à signaler : le client est à jour de ses commandes habituelles."]
    lignes += ["", "STOCK À ÉCOULER"]
    lignes += [
        f"- {s.libelle} — lot {s.lot_id}, DLC {_date_fr(s.dlc)} — {_euros(s.prix_unitaire_ht)} → "
        f"{_euros(s.prix_remise_ht)} HT (-{s.remise_pct} %) : {s.argument}"
        for s in fiche.stock_a_ecouler
    ] or ["- Aucun produit à écouler pertinent pour ce client."]
    if fiche.suggestions:
        lignes += ["", "À PROPOSER AUSSI"]
        lignes += [f"- {s.libelle} ({_euros(s.prix_unitaire_ht)} HT) : {s.argument}" for s in fiche.suggestions]
    lignes += ["", "ACCROCHES"] + [f"« {a} »" for a in fiche.accroches]
    mention = f"Rédigée par IA ({fiche.modele})" if fiche.mode == "ia" else "Rédigée sans IA (mode repli)"
    lignes += ["", f"[{mention}{' — ' + fiche.avertissement if fiche.avertissement else ''}]"]
    return "\n".join(lignes)


# ---------------------------------------------------------------------------
# Formatage français
# ---------------------------------------------------------------------------


def _euros(montant: float) -> str:
    texte = f"{montant:,.2f}".replace(",", " ").replace(".", ",")
    return f"{texte} €"


def _nombre(x: float) -> str:
    return f"{x:g}".replace(".", ",")


def _quantite(x: float, unite: str) -> str:
    """« 2 cartons », « 1 seau », « 6 kg », « 3 plateaux »."""
    if x >= 2 and unite not in ("kg", "L") and not unite.endswith(("s", "x")):
        unite += "x" if unite.endswith("eau") else "s"
    return f"{_nombre(x)} {unite}"


def _clients(n: int) -> str:
    return "1 autre client" if n == 1 else f"{n} autres clients"


def _minuscule(libelle: str) -> str:
    """Met en minuscule la première lettre d'un libellé pour l'insérer dans une phrase."""
    return libelle[:1].lower() + libelle[1:]


def _jours(n: float) -> str:
    return "jours" if n == 1 else f"{_nombre(n)} jours"


def _date_fr(d: date | str) -> str:
    if isinstance(d, str):
        d = date.fromisoformat(d)
    return d.strftime("%d/%m/%Y")


def _liste_fr(elements: list[str]) -> str:
    if len(elements) <= 1:
        return "".join(elements)
    return ", ".join(elements[:-1]) + " et " + elements[-1]
