"""Assemblage du rapport de diagnostic."""

from __future__ import annotations

import time
from collections.abc import Callable
from datetime import datetime

from copilote.datahub import DataSource

from .connexion import Chrono, debut_periode, lire_source, verifier_contrat
from .modeles import (
    Gravite,
    MesureRessource,
    RapportDiagnostic,
    ResultatRegle,
    StatutDiagnostic,
    Traitement,
    VerificationContrat,
)
from .qualite import controler_qualite, mesurer_volumes


def diagnostiquer(
    source: DataSource,
    periode_analyse_jours: int,
    *,
    maintenant: Callable[[], datetime] = datetime.now,
    chrono: Chrono = time.perf_counter,
) -> RapportDiagnostic:
    """Lit la source, vérifie le contrat et contrôle la qualité des données.

    Ne lève pas d'exception si la source est illisible : le rapport le dit
    (statut « lecture impossible » et message d'erreur par ressource).
    """
    debut = chrono()
    date_reference = source.date_du_jour()
    depuis = debut_periode(date_reference, periode_analyse_jours)
    lecture = lire_source(source, depuis, chrono)
    contrat: tuple[VerificationContrat, ...] = ()
    qualite: tuple[ResultatRegle, ...] = ()
    if lecture.donnees is not None:
        contrat = verifier_contrat(source, lecture.donnees, depuis)
        qualite = controler_qualite(lecture.donnees)
    statut = statut_global(lecture.mesures, contrat, qualite)
    return RapportDiagnostic(
        source=source.nom,
        date_reference=date_reference,
        genere_le=maintenant().replace(microsecond=0),
        duree_totale_ms=round((chrono() - debut) * 1000),
        periode_analyse_jours=periode_analyse_jours,
        statut=statut,
        resume=resumer(statut, lecture.mesures, contrat, qualite),
        connexion=lecture.mesures,
        contrat=contrat,
        volumes=mesurer_volumes(lecture.donnees) if lecture.donnees is not None else None,
        qualite=qualite,
        enregistrements_ecartes=_nombre_ecartes(qualite),
    )


def statut_global(
    mesures: tuple[MesureRessource, ...],
    contrat: tuple[VerificationContrat, ...],
    qualite: tuple[ResultatRegle, ...],
) -> StatutDiagnostic:
    if any(m.erreur is not None for m in mesures):
        return StatutDiagnostic.LECTURE_IMPOSSIBLE
    if any(not v.reussie for v in contrat) or _nombre(qualite, Gravite.CRITIQUE):
        return StatutDiagnostic.A_CORRIGER
    if _nombre(qualite, Gravite.ALERTE):
        return StatutDiagnostic.A_SURVEILLER
    return StatutDiagnostic.CONFORME


def resumer(
    statut: StatutDiagnostic,
    mesures: tuple[MesureRessource, ...],
    contrat: tuple[VerificationContrat, ...],
    qualite: tuple[ResultatRegle, ...],
) -> str:
    """Une phrase lisible par un responsable : ce qui va, ce qui ne va pas."""
    if statut is StatutDiagnostic.LECTURE_IMPOSSIBLE:
        en_erreur = [m for m in mesures if m.erreur is not None]
        autres = {1: "", 2: " (et 1 autre ressource en erreur)"}.get(
            len(en_erreur), f" (et {len(en_erreur) - 1} autres ressources en erreur)"
        )
        return f"Lecture des données impossible. {en_erreur[0].libelle} : {en_erreur[0].erreur}{autres}"
    duree = sum(m.duree_ms for m in mesures) / 1000
    morceaux = [f"Données lues en {duree:.1f} s".replace(".", ",")]
    if echecs := sum(not v.reussie for v in contrat):
        morceaux.append(_pluriel(echecs, "point") + " du contrat non " + _accord(echecs, "respecté"))
    critiques, alertes = _regles_en_defaut(qualite, Gravite.CRITIQUE), _regles_en_defaut(qualite, Gravite.ALERTE)
    if critiques or alertes:
        morceaux.append(f"{_pluriel(critiques, 'contrôle')} {_accord(critiques, 'critique')}")
        morceaux.append(_pluriel(alertes, "alerte"))
    else:
        morceaux.append("aucune anomalie notable")
    phrase = ", ".join(morceaux) + "."
    if ecartes := _nombre_ecartes(qualite):
        phrase += f" {_pluriel(ecartes, 'enregistrement')} {_accord(ecartes, 'écarté')} des analyses."
    return phrase


def _accord(nombre: int, mot: str) -> str:
    return mot + "s" if nombre > 1 else mot


def _pluriel(nombre: int, mot: str) -> str:
    return f"{nombre} {_accord(nombre, mot)}"


def _nombre(qualite: tuple[ResultatRegle, ...], gravite: Gravite) -> int:
    return sum(r.nombre for r in qualite if r.gravite is gravite)


def _regles_en_defaut(qualite: tuple[ResultatRegle, ...], gravite: Gravite) -> int:
    return sum(1 for r in qualite if r.gravite is gravite and r.nombre)


def _nombre_ecartes(qualite: tuple[ResultatRegle, ...]) -> int:
    return sum(r.nombre for r in qualite if r.traitement is Traitement.ECARTE)
