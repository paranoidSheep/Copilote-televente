"""Tests de la source de données simulée et du générateur."""

from __future__ import annotations

import json
from datetime import timedelta

import pytest

from datahub import DataSourceError, get_datasource
from datahub.base import ClientIntrouvable
from datahub.mock import CHEMIN_PAR_DEFAUT, MockDataSource
from scripts.generer_donnees_mock import generer


def test_volumes(mock_source):
    assert len(mock_source.get_clients()) == 30
    produits = mock_source.get_products()
    assert len(produits) == 80
    familles = {p.famille for p in produits}
    assert familles == {"frais", "surgele"}


def test_types_de_clients_varies(mock_source):
    types = {c.type for c in mock_source.get_clients()}
    assert {"Restaurant", "Cantine scolaire", "Boulangerie-pâtisserie"} <= types
    assert len(types) >= 6


def test_historique_sur_six_mois(mock_source):
    commandes = mock_source.get_order_history()
    assert commandes == sorted(commandes, key=lambda c: (c.date, c.id))
    etendue = commandes[-1].date - commandes[0].date
    assert timedelta(days=170) <= etendue <= timedelta(days=185)
    assert commandes[-1].date < mock_source.date_du_jour()  # pas de commande « future »


def test_chaque_client_a_un_historique(mock_source):
    for c in mock_source.get_clients():
        assert len(mock_source.get_order_history(c.id)) >= 10, c.id


def test_commandes_coherentes_avec_le_catalogue(mock_source):
    codes = {p.code for p in mock_source.get_products()}
    clients = {c.id for c in mock_source.get_clients()}
    for cmd in mock_source.get_order_history():
        assert cmd.client_id in clients
        assert cmd.lignes and cmd.montant_ht > 0
        assert {l.produit_code for l in cmd.lignes} <= codes


def test_filtres_historique(mock_source):
    depuis = mock_source.date_du_jour() - timedelta(days=30)
    commandes = mock_source.get_order_history("C001", depuis=depuis)
    assert commandes
    assert all(c.client_id == "C001" and c.date >= depuis for c in commandes)


def test_client_inconnu(mock_source):
    with pytest.raises(ClientIntrouvable):
        mock_source.get_client("C999")
    with pytest.raises(ClientIntrouvable):
        mock_source.get_order_history("C999")


def test_stock_avec_lots_proches_de_la_peremption(mock_source):
    lots = mock_source.get_stock()
    codes = {p.code for p in mock_source.get_products()}
    assert all(l.produit_code in codes and l.quantite > 0 for l in lots)
    aujourd_hui = mock_source.date_du_jour()
    proches = [l for l in lots if (l.dlc - aujourd_hui).days <= 3]
    assert len(proches) >= 5  # la démo doit avoir des produits à écouler


def test_fichier_a_jour_avec_le_generateur():
    """Le JSON versionné doit correspondre exactement à la sortie du script seedé."""
    sur_disque = json.loads(CHEMIN_PAR_DEFAUT.read_text(encoding="utf-8"))
    assert sur_disque == generer()


def test_generateur_deterministe():
    assert generer(7) == generer(7)
    assert generer(7) != generer(8)


def test_selection_de_la_source(monkeypatch):
    monkeypatch.setenv("DATASOURCE", "mock")
    assert isinstance(get_datasource(), MockDataSource)
    with pytest.raises(DataSourceError):
        get_datasource("ftp")


def test_fichier_absent(tmp_path):
    with pytest.raises(DataSourceError):
        MockDataSource(tmp_path / "absent.json")
