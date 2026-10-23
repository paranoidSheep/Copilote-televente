"""Assemblage de la fiche : rédaction + analyses -> fiche finale, avec garde-fous.

Principe : l'IA rédige, les analyses font foi.
- un code produit absent des analyses est écarté (pas d'invention possible) ;
- une remise supérieure à la remise suggérée est ramenée à ce maximum ;
- une offre (stock, suggestion) refusée récemment par le client n'est pas reproposée, et une
  accroche qui la vante est retirée ;
- si ces corrections vident la sélection de stock, elle est complétée depuis les analyses ;
- un rappel promis au client figure toujours dans les points d'attention ;
- prix, DLC, quantités et indicateurs viennent exclusivement des analyses.
Chaque correction est consignée dans `Fiche.garde_fous`, typée (voir `TypeCorrection`) : elle
est affichée pour la transparence et comptée par le banc d'évaluation de la qualité de l'IA.
"""

from __future__ import annotations

import re
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass, field
from datetime import datetime
from typing import Protocol

from copilote.analyses import ContexteClient, ProduitManquant, PropositionStock, SuggestionCroisee

from . import formatage as fmt
from .modeles import (
    Correction,
    Fiche,
    ManquantFiche,
    ModeFiche,
    Redaction,
    RedactionManquant,
    RedactionStock,
    RedactionSuggestion,
    StockFiche,
    SuggestionFiche,
    TypeCorrection,
)
from .panier import construire_panier
from .rendu import fiche_en_texte
from .repli import MAX_ACCROCHES, MAX_MANQUANTS, MAX_STOCK, MAX_SUGGESTIONS, accroches_gabarits, argument_stock
from .trace import TraceExecution

MAX_POINTS_ATTENTION = 4
MIN_STOCK = 2  # nombre de produits à écouler visé quand des propositions ont été retirées
QUANTITE_DEFAUT_STOCK = 1.0


class _AvecCode(Protocol):
    @property
    def code(self) -> str: ...


class _AvecLibelle(Protocol):
    @property
    def libelle(self) -> str: ...


LONGUEUR_MIN_NOM = 6  # en dessous (« pain », « lait »), un nom est trop générique pour conclure
MOTS_DE_LIAISON = {"de", "du", "des", "à", "au", "aux", "en", "et", "la", "le", "les"}


def noms_usuels(libelle: str) -> list[str]:
    """Façons de nommer un produit au téléphone, de la plus précise à la plus courte.

    « Cordon bleu de volaille, carton de 40 » -> [« cordon bleu de volaille », « cordon bleu », « cordon »]
    (sans conditionnement ni mot de liaison final, au moins `LONGUEUR_MIN_NOM` caractères).
    """
    mots: list[str] = []
    for mot in libelle.lower().replace(",", " , ").split():
        if mot == "," or any(c.isdigit() for c in mot):
            break
        mots.append(mot)
    noms: list[str] = []
    for taille in range(len(mots), 0, -1):
        prefixe = mots[:taille]
        while prefixe and prefixe[-1] in MOTS_DE_LIAISON:
            prefixe = prefixe[:-1]
        nom = " ".join(prefixe)
        if len(nom) >= LONGUEUR_MIN_NOM and nom not in noms:
            noms.append(nom)
    return noms


def mentionne(texte: str, nom: str) -> bool:
    return re.search(rf"\b{re.escape(nom)}\b", texte.lower()) is not None


@dataclass
class _Assembleur:
    """Applique les garde-fous et consigne chaque correction."""

    contexte: ContexteClient
    garde_fous: list[Correction] = field(default_factory=list)
    retires: dict[str, str] = field(default_factory=dict)  # offres retirées : code -> libellé

    def corriger(self, type_: TypeCorrection, message: str, codes: Sequence[str] = ()) -> None:
        self.garde_fous.append(Correction(type=type_, message=message, codes=list(codes)))

    @property
    def refuses(self) -> set[str]:
        return set(self.contexte.appels.codes_refuses_recemment)

    def selectionner[R: _AvecCode, Ref: _AvecLibelle, Sortie](
        self,
        rubrique: str,
        choix_ia: Sequence[R],
        *,
        references: Mapping[str, Ref],
        maximum: int,
        construire: Callable[[R, Ref], Sortie],
        exclure_refus: bool = True,
    ) -> list[Sortie]:
        """Filtre la sélection de l'IA : doublons, codes inconnus, offres refusées, nombre maximum."""
        retenus: list[Sortie] = []
        vus: set[str] = set()
        for choix in choix_ia:
            if choix.code in vus:
                continue
            vus.add(choix.code)
            reference = references.get(choix.code)
            if reference is None:
                message = f"{rubrique} : produit {choix.code} ignoré (absent des données)"
                self.corriger(TypeCorrection.PRODUIT_INCONNU, message, [choix.code])
                continue
            if exclure_refus and choix.code in self.refuses:
                message = f"{rubrique} : produit {choix.code} retiré (refusé récemment par le client)"
                self.corriger(TypeCorrection.OFFRE_REFUSEE, message, [choix.code])
                self.retires[choix.code] = reference.libelle
                continue
            if len(retenus) == maximum:
                self.corriger(TypeCorrection.SELECTION_LIMITEE, f"{rubrique} : sélection limitée à {maximum} produits")
                break
            retenus.append(construire(choix, reference))
        return retenus

    def manquant(self, choix: RedactionManquant, ref: ProduitManquant) -> ManquantFiche:
        return ManquantFiche(**ref.model_dump(), commentaire=choix.commentaire.strip())

    def stock(self, choix: RedactionStock, ref: PropositionStock) -> StockFiche:
        remise = max(0, min(choix.remise_pct, ref.remise_suggeree_pct))
        if remise != choix.remise_pct:
            message = f"Stock : remise sur {ref.code} ramenée de {choix.remise_pct} % à {remise} % (maximum autorisé)"
            self.corriger(TypeCorrection.REMISE_PLAFONNEE, message, [ref.code])
        quantites_habituelles = {p.code: p.quantite_habituelle for p in self.contexte.habitudes.produits_recurrents}
        return StockFiche(
            **ref.model_dump(),
            remise_pct=remise,
            prix_propose_ht=round(ref.prix_unitaire_ht * (1 - remise / 100), 2),
            quantite_conseillee=min(quantites_habituelles.get(ref.code, QUANTITE_DEFAUT_STOCK), ref.quantite_lot),
            argument=choix.argument.strip(),
        )

    def completer_stock(self, retenus: list[StockFiche], nb_proposes: int) -> list[StockFiche]:
        """Si les garde-fous ont trop réduit la sélection de l'IA, la complète avec les analyses.

        Ne s'applique que si l'IA avait proposé des produits : une sélection vide
        voulue par l'IA est respectée.
        """
        minimum = min(MIN_STOCK, nb_proposes)
        if len(retenus) >= minimum:
            return []
        deja = {s.code for s in retenus}
        candidats = [p for p in self.contexte.stock.produits if p.code not in deja and p.code not in self.refuses][
            : minimum - len(retenus)
        ]
        if candidats:
            message = (
                f"Stock : {fmt.pluriel(len(candidats), 'produit')} ajouté(s) depuis les analyses "
                "pour compléter la sélection"
            )
            self.corriger(TypeCorrection.STOCK_COMPLETE, message, [p.code for p in candidats])
        return [
            self.stock(RedactionStock(code=p.code, remise_pct=p.remise_suggeree_pct, argument=argument_stock(p)), p)
            for p in candidats
        ]

    def points_attention(self, proposes: Sequence[str]) -> list[str]:
        """Points d'attention de l'IA, complétés des faits que la fiche ne doit jamais omettre."""
        points = [p.strip() for p in proposes if p.strip()][:MAX_POINTS_ATTENTION]
        rappel = self.contexte.appels.rappel_prevu
        if rappel is not None and not any("rappel" in p.lower() for p in points):
            points.insert(0, f"Le client a demandé à être rappelé le {fmt.date_longue(rappel)}.")
            self.corriger(TypeCorrection.RAPPEL_AJOUTE, "Points d'attention : rappel promis ajouté")
        return points

    def suggestion(self, choix: RedactionSuggestion, ref: SuggestionCroisee) -> SuggestionFiche:
        return SuggestionFiche(**ref.model_dump(), argument=choix.argument.strip())

    def accroches(
        self,
        proposees: Sequence[str],
        manquants: list[ManquantFiche],
        stock: list[StockFiche],
        suggestions: list[SuggestionFiche],
    ) -> list[str]:
        accroches = [a.strip() for a in proposees if a.strip()]
        # Une accroche qui vante une offre retirée ferait reproposer au téléphone un produit refusé.
        # Un nom partagé avec un produit conservé (« escalope ») ne suffit pas à conclure.
        libelles = [p.libelle for p in manquants] + [p.libelle for p in stock] + [p.libelle for p in suggestions]
        conserves = {n for libelle in libelles for n in noms_usuels(libelle)}
        noms_retires = {code: [n for n in noms_usuels(l) if n not in conserves] for code, l in self.retires.items()}
        for accroche in list(accroches):
            cites = [code for code, noms in noms_retires.items() if any(mentionne(accroche, n) for n in noms)]
            if cites:
                accroches.remove(accroche)
                message = f"Accroches : accroche retirée, elle proposait {', '.join(cites)} (refusé récemment)"
                self.corriger(TypeCorrection.ACCROCHE_RETIREE, message, cites)
        if len(accroches) > MAX_ACCROCHES:
            self.corriger(TypeCorrection.ACCROCHES_LIMITEES, f"Accroches : limitées à {MAX_ACCROCHES}")
            accroches = accroches[:MAX_ACCROCHES]
        if len(accroches) < 2:
            complements = accroches_gabarits(
                self.contexte.habitudes, manquants, [(s, s.remise_pct) for s in stock], suggestions
            )
            ajout = [a for a in complements if a not in accroches][: 2 - len(accroches)]
            message = f"Accroches : {fmt.pluriel(len(ajout), 'accroche')} ajoutée(s) automatiquement"
            self.corriger(TypeCorrection.ACCROCHES_COMPLETEES, message)
            accroches += ajout
        return accroches


def assembler_fiche(
    contexte: ContexteClient,
    redaction: Redaction,
    *,
    mode: ModeFiche,
    genere_le: datetime,
    modele: str | None = None,
    avertissement: str | None = None,
    trace: TraceExecution | None = None,
) -> Fiche:
    a = _Assembleur(contexte)
    manquants = a.selectionner(
        "Produits manquants",
        redaction.produits_manquants,
        references={p.code: p for p in contexte.manquants.produits},
        maximum=MAX_MANQUANTS,
        construire=a.manquant,
        exclure_refus=False,  # un produit habituel reste à proposer, même refusé une fois
    )
    stock = a.selectionner(
        "Stock",
        redaction.stock_a_ecouler,
        references={p.code: p for p in contexte.stock.produits},
        maximum=MAX_STOCK,
        construire=a.stock,
    )
    stock += a.completer_stock(stock, len(redaction.stock_a_ecouler))
    suggestions = a.selectionner(
        "Suggestions",
        redaction.suggestions,
        references={p.code: p for p in contexte.suggestions.produits},
        maximum=MAX_SUGGESTIONS,
        construire=a.suggestion,
    )
    fiche = Fiche(
        client=contexte.habitudes.client,
        date_du_jour=contexte.habitudes.date_du_jour,
        genere_le=genere_le.replace(microsecond=0),
        mode=mode,
        modele=modele,
        avertissement=avertissement,
        resume_habitudes=redaction.resume_habitudes.strip(),
        habitudes=contexte.habitudes,
        produits_manquants=manquants,
        stock_a_ecouler=stock,
        suggestions=suggestions,
        accroches=a.accroches(redaction.accroches, manquants, stock, suggestions),
        points_attention=a.points_attention(redaction.points_attention),
        appels_precedents=contexte.appels,
        panier=construire_panier(manquants, stock, suggestions),
        garde_fous=a.garde_fous,
        trace=trace,
    )
    fiche.texte = fiche_en_texte(fiche)
    return fiche
