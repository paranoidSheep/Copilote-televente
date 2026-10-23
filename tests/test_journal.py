"""Journal des appels : validation, stockage SQLite/mémoire, statistiques."""

from __future__ import annotations

from datetime import date, datetime
from pathlib import Path

import pytest
from pydantic import ValidationError

from copilote.journal import (
    DepotJournal,
    DepotMemoire,
    DepotSQLite,
    Issue,
    LigneCompteRendu,
    NouveauCompteRendu,
    Origine,
    Reponse,
    calculer_statistiques,
)


def ligne(code: str, origine: Origine, reponse: Reponse, quantite: float = 2, remise: int = 0) -> LigneCompteRendu:
    return LigneCompteRendu(
        code=code,
        libelle=f"Produit {code}",
        unite="kg",
        origine=origine,
        reponse=reponse,
        quantite=quantite if reponse is Reponse.ACCEPTE else 0,
        prix_unitaire_ht=10,
        remise_pct=remise,
    )


def commande(client_id: str = "C001", vendeur: str = "Julie") -> NouveauCompteRendu:
    return NouveauCompteRendu(
        client_id=client_id,
        televendeur=vendeur,
        issue=Issue.COMMANDE,
        lignes=[
            ligne("A", Origine.MANQUANT, Reponse.ACCEPTE),
            ligne("B", Origine.STOCK, Reponse.ACCEPTE, 3, 20),
            ligne("C", Origine.SUGGESTION, Reponse.REFUSE),
        ],
    )


def test_montants():
    cr = commande()
    assert cr.lignes[1].prix_net_ht == 8.0
    assert cr.montant_accepte_ht == 20 + 24  # le refus ne compte pas


@pytest.mark.parametrize(
    "donnees",
    [
        {"issue": "rappeler"},  # date de rappel obligatoire
        {"issue": "commande", "lignes": []},  # une commande sans produit accepté
        {"issue": "pas_de_besoin", "televendeur": ""},
        {"issue": "pas_de_besoin", "inconnu": 1},  # champ inconnu refusé
    ],
)
def test_validations(donnees):
    with pytest.raises(ValidationError):
        NouveauCompteRendu.model_validate({"client_id": "C001", "televendeur": "Julie", **donnees})


def test_quantite_obligatoire_si_accepte():
    with pytest.raises(ValidationError):
        LigneCompteRendu(
            code="A", libelle="A", origine=Origine.STOCK, reponse=Reponse.ACCEPTE, quantite=0, prix_unitaire_ht=1
        )


@pytest.fixture(params=["memoire", "sqlite"])
def depot(request, tmp_path: Path) -> DepotJournal:
    return DepotMemoire() if request.param == "memoire" else DepotSQLite(tmp_path / "journal.sqlite3")


def test_depot_aller_retour_et_filtres(depot: DepotJournal):
    premier = depot.enregistrer(commande("C001"), datetime(2026, 10, 20, 9, 0))
    depot.enregistrer(
        NouveauCompteRendu(client_id="C002", televendeur="Karim", issue=Issue.RAPPELER, rappel_le=date(2026, 10, 24)),
        datetime(2026, 10, 22, 9, 0),
    )
    depot.enregistrer(commande("C001"), datetime(2026, 10, 23, 9, 0))

    assert premier.id >= 1 and premier.lignes == commande().lignes
    assert depot.obtenir(premier.id) == premier
    assert depot.obtenir(999) is None
    tous = depot.lister()
    assert [cr.cree_le.day for cr in tous] == [23, 22, 20]  # du plus récent au plus ancien
    assert [cr.client_id for cr in depot.lister(client_id="C001")] == ["C001", "C001"]
    assert len(depot.lister(depuis=datetime(2026, 10, 21))) == 2
    assert len(depot.lister(limite=1)) == 1
    assert depot.lister(client_id="C002")[0].rappel_le == date(2026, 10, 24)


def test_sqlite_persiste_entre_instances(tmp_path: Path):
    chemin = tmp_path / "sous" / "journal.sqlite3"
    DepotSQLite(chemin).enregistrer(commande(), datetime(2026, 10, 23, 9, 0))
    assert len(DepotSQLite(chemin).lister()) == 1


def test_statistiques():
    depot = DepotMemoire()
    depot.enregistrer(commande("C001", "Julie"), datetime(2026, 10, 22, 9, 0))
    depot.enregistrer(commande("C002", "Karim"), datetime(2026, 10, 23, 9, 0))
    depot.enregistrer(
        NouveauCompteRendu(client_id="C003", televendeur="Julie", issue=Issue.INJOIGNABLE),
        datetime(2026, 10, 23, 10, 0),
    )
    stats = calculer_statistiques(depot.lister())
    assert stats.nb_appels == 3 and stats.nb_clients == 3
    assert stats.issues[Issue.COMMANDE] == 2 and stats.issues[Issue.INJOIGNABLE] == 1
    assert stats.taux_transformation_pct == 67
    assert stats.ca_accepte_ht == 88.0
    assert stats.quantite_stock_ecoulee == 6
    par_origine = {o.origine: o for o in stats.par_origine}
    assert par_origine[Origine.SUGGESTION].taux_acceptation_pct == 0
    assert par_origine[Origine.STOCK].ca_accepte_ht == 48.0
    assert [j.appels for j in stats.par_jour] == [1, 2]
    assert stats.par_televendeur[0].appels + stats.par_televendeur[1].appels == 3


def test_statistiques_vides():
    stats = calculer_statistiques([])
    assert stats.nb_appels == 0 and stats.taux_transformation_pct is None and stats.par_origine == []
