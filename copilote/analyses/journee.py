"""La journée du télévendeur : objectifs, agenda des rappels et avancement de la tournée.

Tout est calculé à partir du journal des comptes-rendus et de la file d'appels :
aucun état supplémentaire n'est stocké. Un client est « fait » dès qu'un
compte-rendu a été enregistré pour lui aujourd'hui ; un rappel est « traité »
dès qu'un appel plus récent a eu lieu.
"""

from __future__ import annotations

from collections.abc import Sequence
from datetime import date
from enum import StrEnum

from copilote.domaine import Client
from copilote.journal import CompteRendu, Issue

from .base import Resultat
from .priorisation import FileAppels, PrioriteAppel
from .referentiel import Referentiel
from .regles import ReglesMetier


class StatutRappel(StrEnum):
    EN_RETARD = "en_retard"
    AUJOURDHUI = "aujourdhui"
    A_VENIR = "a_venir"


class RappelAgenda(Resultat):
    client: Client
    rappel_le: date
    statut: StatutRappel
    ecart_jours: int  # négatif : en retard de N jours
    demande_le: date
    demande_par: str
    notes: str


class AgendaRappels(Resultat):
    date_du_jour: date
    en_retard: list[RappelAgenda]
    aujourdhui: list[RappelAgenda]
    a_venir: list[RappelAgenda]


class Objectif(Resultat):
    realise: float
    cible: float
    pct: int  # peut dépasser 100


class ObjectifsJour(Resultat):
    appels: Objectif
    ca_accepte_ht: Objectif
    commandes: int
    taux_transformation_pct: int | None


class EtapeTournee(Resultat):
    client_id: str
    nom: str
    score: int
    fait: bool  # un compte-rendu a été enregistré aujourd'hui pour ce client


class AvancementTournee(Resultat):
    """La tournée suit la file d'appels, par priorité ; elle avance à chaque compte-rendu."""

    total: int
    faits: int
    etapes: list[EtapeTournee]  # du plus au moins prioritaire
    prochain: PrioriteAppel | None


class Journee(Resultat):
    date_du_jour: date
    televendeur: str | None
    objectifs: ObjectifsJour
    agenda: AgendaRappels
    tournee: AvancementTournee


def construire_agenda(
    ref: Referentiel, comptes_rendus: Sequence[CompteRendu], televendeur: str | None = None
) -> AgendaRappels:
    """Rappels promis et non encore traités (le dernier appel au client a fixé un rappel)."""
    derniers: dict[str, CompteRendu] = {}
    for cr in sorted(comptes_rendus, key=lambda c: c.cree_le):
        derniers[cr.client_id] = cr
    entrees: list[RappelAgenda] = []
    for client_id, cr in derniers.items():
        client = ref.clients.get(client_id)
        if client is None or cr.issue is not Issue.RAPPELER or cr.rappel_le is None:
            continue
        if televendeur is not None and client.commercial != televendeur:
            continue
        ecart = (cr.rappel_le - ref.date_du_jour).days
        statut = (
            StatutRappel.EN_RETARD if ecart < 0 else StatutRappel.AUJOURDHUI if ecart == 0 else StatutRappel.A_VENIR
        )
        entrees.append(
            RappelAgenda(
                client=client,
                rappel_le=cr.rappel_le,
                statut=statut,
                ecart_jours=ecart,
                demande_le=cr.cree_le.date(),
                demande_par=cr.televendeur,
                notes=cr.notes,
            )
        )
    entrees.sort(key=lambda e: (e.rappel_le, e.client.nom))
    return AgendaRappels(
        date_du_jour=ref.date_du_jour,
        en_retard=[e for e in entrees if e.statut is StatutRappel.EN_RETARD],
        aujourdhui=[e for e in entrees if e.statut is StatutRappel.AUJOURDHUI],
        a_venir=[e for e in entrees if e.statut is StatutRappel.A_VENIR],
    )


def _objectif(realise: float, cible: float) -> Objectif:
    return Objectif(realise=round(realise, 2), cible=cible, pct=round(100 * realise / cible) if cible else 0)


def objectifs_du_jour(
    comptes_rendus: Sequence[CompteRendu],
    jour: date,
    regles: ReglesMetier,
    televendeur: str | None = None,
    nb_televendeurs: int = 1,
) -> ObjectifsJour:
    """Progression du jour ; pour toute l'équipe (`televendeur` absent), les objectifs s'additionnent."""
    du_jour = [
        cr
        for cr in comptes_rendus
        if cr.cree_le.date() == jour and (televendeur is None or cr.televendeur == televendeur)
    ]
    commandes = sum(cr.issue is Issue.COMMANDE for cr in du_jour)
    equipe = 1 if televendeur is not None else max(1, nb_televendeurs)
    return ObjectifsJour(
        appels=_objectif(len(du_jour), regles.objectif_appels_jour * equipe),
        ca_accepte_ht=_objectif(sum(cr.montant_accepte_ht for cr in du_jour), regles.objectif_ca_jour_ht * equipe),
        commandes=commandes,
        taux_transformation_pct=round(100 * commandes / len(du_jour)) if du_jour else None,
    )


def avancement_tournee(file: FileAppels) -> AvancementTournee:
    ordre = sorted(file.appels, key=lambda a: (-a.score, a.client.nom))
    restants = [a for a in ordre if not a.deja_appele_aujourdhui]
    return AvancementTournee(
        total=len(ordre),
        faits=len(ordre) - len(restants),
        etapes=[
            EtapeTournee(client_id=a.client.id, nom=a.client.nom, score=a.score, fait=a.deja_appele_aujourdhui)
            for a in ordre
        ],
        prochain=restants[0] if restants else None,
    )
