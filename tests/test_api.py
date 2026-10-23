"""Tests de l'API web (en mode repli, sans appel réseau)."""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from api.main import app


@pytest.fixture
def api(monkeypatch):
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    monkeypatch.setenv("DATASOURCE", "mock")
    return TestClient(app)


def test_page_accueil(api):
    reponse = api.get("/")
    assert reponse.status_code == 200
    assert "Copilote télévente" in reponse.text


def test_sante(api):
    corps = api.get("/sante").json()
    assert corps["source_donnees"] == "mock"
    assert corps["mode"] == "repli"


def test_liste_clients(api):
    clients = api.get("/clients").json()
    assert len(clients) == 30
    assert {"id", "nom", "type", "ville"} <= set(clients[0])


def test_fiche_client(api):
    reponse = api.get("/clients/C001/fiche")
    assert reponse.status_code == 200
    fiche = reponse.json()
    assert fiche["client"]["id"] == "C001"
    assert fiche["mode"] == "repli"
    for cle in ("habitudes", "produits_manquants", "stock_a_ecouler", "suggestions", "accroches", "texte"):
        assert cle in fiche
    # deuxième appel servi par le cache, régénération possible
    assert api.get("/clients/C001/fiche").json()["genere_le"] == fiche["genere_le"]
    assert api.get("/clients/C001/fiche?regenerer=true").status_code == 200


def test_fiche_client_inconnu(api):
    assert api.get("/clients/C999/fiche").status_code == 404
