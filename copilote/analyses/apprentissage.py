"""Apprentissage des retours clients : ce qui est accepté, ou refusé, au téléphone.

Chaque compte-rendu indique, pour chaque offre de stock ou suggestion, si le
client l'a acceptée ou refusée. On en tire un taux d'acceptation par produit et
par type d'établissement (« la crème liquide plaît aux pizzerias »), qui module
le classement des propositions suivantes pour les clients de ce type.

Pour ne pas conclure sur un ou deux appels, le taux est **lissé** vers le taux
global (moyenne pondérée par `apprentissage_lissage` propositions fictives) et
n'est retenu qu'à partir de `apprentissage_min_propositions` propositions.
Chaque ajustement est justifié en clair, dans la fiche et pour l'IA.
"""

from __future__ import annotations

from collections import defaultdict
from collections.abc import Iterable, Mapping
from dataclasses import dataclass, field
from datetime import date, timedelta

from copilote.domaine import Client
from copilote.journal import CompteRendu, Origine, Reponse

from .base import Resultat
from .regles import REGLES_PAR_DEFAUT, ReglesMetier

ORIGINES_APPRISES = (Origine.STOCK, Origine.SUGGESTION)  # les habituels ne sont pas des « offres »


class RetourClients(Resultat):
    """Ce que les établissements du même type ont répondu à cette offre."""

    sens: int  # +1 souvent accepté, -1 souvent refusé, 0 neutre
    acceptes: int
    proposes: int
    taux_acceptation_pct: int
    justification: str


@dataclass
class _Compte:
    acceptes: int = 0
    proposes: int = 0

    def ajouter(self, accepte: bool) -> None:
        self.proposes += 1
        self.acceptes += accepte

    @property
    def taux(self) -> float:
        return self.acceptes / self.proposes if self.proposes else 0.0


@dataclass(frozen=True)
class ModeleAcceptation:
    """Taux d'acceptation observés, par (produit, type d'établissement) et en moyenne."""

    par_produit_et_type: Mapping[tuple[str, str], _Compte] = field(default_factory=dict)
    global_: _Compte = field(default_factory=_Compte)
    regles: ReglesMetier = REGLES_PAR_DEFAUT

    @property
    def vide(self) -> bool:
        return self.global_.proposes == 0

    def retour(self, code: str, type_client: str) -> RetourClients | None:
        """Retour des clients de ce type sur ce produit ; `None` s'il est trop peu proposé."""
        compte = self.par_produit_et_type.get((code, type_client))
        regles = self.regles
        if compte is None or compte.proposes < regles.apprentissage_min_propositions:
            return None
        lissage = regles.apprentissage_lissage
        lisse = (compte.acceptes + lissage * self.global_.taux) / (compte.proposes + lissage)
        ecart = lisse - self.global_.taux
        sens = 1 if ecart >= regles.apprentissage_ecart else -1 if ecart <= -regles.apprentissage_ecart else 0
        constat = f"Accepté {compte.acceptes} fois sur {compte.proposes} par des établissements « {type_client} »"
        conclusion = {1: "mis en avant", -1: "proposé en dernier", 0: "dans la moyenne"}[sens]
        return RetourClients(
            sens=sens,
            acceptes=compte.acceptes,
            proposes=compte.proposes,
            taux_acceptation_pct=round(100 * compte.taux),
            justification=f"{constat} : {conclusion}",
        )


def apprendre(
    comptes_rendus: Iterable[CompteRendu],
    clients: Mapping[str, Client],
    date_du_jour: date,
    regles: ReglesMetier = REGLES_PAR_DEFAUT,
) -> ModeleAcceptation:
    """Compte les offres acceptées et refusées sur la fenêtre d'apprentissage.

    Les lignes « sans réponse » sont ignorées : l'offre n'a pas été faite, ou pas tranchée.
    """
    debut = date_du_jour - timedelta(days=regles.apprentissage_fenetre_jours)
    par_cle: dict[tuple[str, str], _Compte] = defaultdict(_Compte)
    global_ = _Compte()
    for compte_rendu in comptes_rendus:
        client = clients.get(compte_rendu.client_id)
        if client is None or not debut <= compte_rendu.cree_le.date() <= date_du_jour:
            continue
        for ligne in compte_rendu.lignes:
            if ligne.origine not in ORIGINES_APPRISES or ligne.reponse is Reponse.SANS_REPONSE:
                continue
            accepte = ligne.reponse is Reponse.ACCEPTE
            par_cle[(ligne.code, client.type)].ajouter(accepte)
            global_.ajouter(accepte)
    return ModeleAcceptation(par_produit_et_type=dict(par_cle), global_=global_, regles=regles)


AUCUN_APPRENTISSAGE = ModeleAcceptation()
