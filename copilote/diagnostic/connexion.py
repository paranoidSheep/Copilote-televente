"""Lecture chronométrée de la source et vérification du contrat d'interface.

Ces vérifications interrogent réellement la source (le datahub en production) :
elles répondent à « le datahub est-il joignable, rapide, et respecte-t-il le
contrat attendu (filtres, 404, lignes de commande…) ? ».
"""

from __future__ import annotations

from collections.abc import Callable, Sized
from dataclasses import dataclass
from datetime import date, timedelta

from copilote.datahub import DataSource
from copilote.domaine import ClientIntrouvable, ErreurCopilote

from .modeles import MesureRessource, VerificationContrat
from .qualite import DonneesBrutes

type Chrono = Callable[[], float]

IDENTIFIANT_CLIENT_INEXISTANT = "__client-inexistant-diagnostic__"


@dataclass(frozen=True, slots=True)
class Lecture:
    mesures: tuple[MesureRessource, ...]
    donnees: DonneesBrutes | None  # None si au moins une ressource est illisible


def _mesurer[T: Sized](
    ressource: str, libelle: str, appel: Callable[[], T], chrono: Chrono
) -> tuple[MesureRessource, T | None]:
    debut = chrono()
    try:
        valeur = appel()
    except (ErreurCopilote, OSError) as exc:
        duree = round((chrono() - debut) * 1000)
        return MesureRessource(ressource=ressource, libelle=libelle, duree_ms=duree, volume=None, erreur=str(exc)), None
    duree = round((chrono() - debut) * 1000)
    mesure = MesureRessource(ressource=ressource, libelle=libelle, duree_ms=duree, volume=len(valeur), erreur=None)
    return mesure, valeur


def lire_source(source: DataSource, depuis: date, chrono: Chrono) -> Lecture:
    """Lit les quatre ressources utilisées par le copilote, en mesurant chacune."""
    m_clients, clients = _mesurer("clients", "Clients", source.get_clients, chrono)
    m_produits, produits = _mesurer("produits", "Catalogue produits", source.get_products, chrono)
    m_commandes, commandes = _mesurer(
        "commandes", "Historique des commandes", lambda: source.get_order_history(depuis=depuis), chrono
    )
    m_lots, lots = _mesurer("stock", "Stock par lot", source.get_stock, chrono)
    mesures = (m_clients, m_produits, m_commandes, m_lots)
    if clients is None or produits is None or commandes is None or lots is None:
        return Lecture(mesures, None)
    donnees = DonneesBrutes(
        date_du_jour=source.date_du_jour(),
        clients=tuple(clients),
        produits=tuple(produits),
        commandes=tuple(commandes),
        lots=tuple(lots),
    )
    return Lecture(mesures, donnees)


def verifier_contrat(source: DataSource, donnees: DonneesBrutes, depuis: date) -> tuple[VerificationContrat, ...]:
    """Points du contrat vérifiables de l'extérieur, sur les données réelles."""
    return (
        _fiche_client_unitaire(source, donnees),
        _client_inconnu(source),
        _filtre_client(source, donnees, depuis),
        _filtre_date(donnees, depuis),
        _lignes_presentes(donnees),
    )


def _verification(libelle: str, reussie: bool, detail: str) -> VerificationContrat:
    return VerificationContrat(libelle=libelle, reussie=reussie, detail=detail)


def _fiche_client_unitaire(source: DataSource, donnees: DonneesBrutes) -> VerificationContrat:
    libelle = "Lecture d'un client par son identifiant"
    if not donnees.clients:
        return _verification(libelle, False, "Aucun client reçu : vérification impossible.")
    attendu = donnees.clients[0]
    try:
        recu = source.get_client(attendu.id)
    except ErreurCopilote as exc:
        return _verification(libelle, False, f"{attendu.id} : {exc}")
    if recu != attendu:
        return _verification(libelle, False, f"{attendu.id} : la fiche diffère de celle de la liste des clients.")
    return _verification(libelle, True, f"{attendu.id} : identique à la liste des clients.")


def _client_inconnu(source: DataSource) -> VerificationContrat:
    libelle = "Client inexistant signalé comme introuvable (404)"
    try:
        source.get_client(IDENTIFIANT_CLIENT_INEXISTANT)
    except ClientIntrouvable:
        return _verification(libelle, True, "Réponse « introuvable » comme attendu.")
    except ErreurCopilote as exc:
        return _verification(libelle, False, f"Erreur inattendue : {exc}")
    return _verification(libelle, False, "Un client a été renvoyé pour un identifiant qui n'existe pas.")


def _filtre_client(source: DataSource, donnees: DonneesBrutes, depuis: date) -> VerificationContrat:
    libelle = "Filtre des commandes par client (client_id)"
    connus = {c.id for c in donnees.clients}
    client_id = next((c.client_id for c in reversed(donnees.commandes) if c.client_id in connus), None)
    if client_id is None:
        return _verification(libelle, False, "Aucune commande reçue : vérification impossible.")
    attendues = {c.id for c in donnees.commandes if c.client_id == client_id}
    try:
        recues = source.get_order_history(client_id=client_id, depuis=depuis)
    except ErreurCopilote as exc:
        return _verification(libelle, False, f"{client_id} : {exc}")
    autres = sorted({c.client_id for c in recues} - {client_id})
    if autres:
        return _verification(libelle, False, f"{client_id} : commandes d'autres clients reçues ({', '.join(autres)}).")
    if {c.id for c in recues} != attendues:
        return _verification(
            libelle, False, f"{client_id} : {len(recues)} commandes reçues, {len(attendues)} attendues."
        )
    return _verification(libelle, True, f"{client_id} : {len(recues)} commandes, toutes du client.")


def _filtre_date(donnees: DonneesBrutes, depuis: date) -> VerificationContrat:
    libelle = "Filtre des commandes par date (depuis)"
    anterieures = [c for c in donnees.commandes if c.date < depuis]
    if anterieures:
        return _verification(
            libelle, False, f"{len(anterieures)} commandes antérieures au {depuis:%d/%m/%Y} reçues malgré le filtre."
        )
    return _verification(libelle, True, f"Aucune commande antérieure au {depuis:%d/%m/%Y}.")


def _lignes_presentes(donnees: DonneesBrutes) -> VerificationContrat:
    libelle = "Lignes de commande incluses dans l'historique"
    sans_lignes = [c.id for c in donnees.commandes if not c.lignes]
    if sans_lignes:
        exemples = ", ".join(sans_lignes[:3])
        return _verification(libelle, False, f"{len(sans_lignes)} commandes sans aucune ligne (ex. {exemples}).")
    lignes = sum(len(c.lignes) for c in donnees.commandes)
    return _verification(libelle, True, f"{lignes:,} lignes reçues.".replace(",", "\u202f"))


def debut_periode(date_du_jour: date, jours: int) -> date:
    return date_du_jour - timedelta(days=jours)
