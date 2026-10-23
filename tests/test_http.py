"""Tests du squelette de client REST, sans réseau (transport httpx simulé)."""

from __future__ import annotations

import httpx
import pytest

from datahub import DataSourceError, get_datasource
from datahub.base import ClientIntrouvable
from datahub.http import HttpDataSource

CLIENT = {"id": "42", "nom": "Chez Test", "type": "Restaurant", "ville": "Lyon",
          "contact": "M. X", "telephone": "04", "commercial": "Julie"}


def faire_source(gestionnaire, requetes):
    def transport(requete: httpx.Request) -> httpx.Response:
        requetes.append(requete)
        return gestionnaire(requete)

    return HttpDataSource("https://datahub.test/api", "secret", transport=httpx.MockTransport(transport))


def test_lecture_seule_et_authentification():
    requetes = []

    def gestionnaire(req):
        if req.url.path.endswith("/clients"):
            return httpx.Response(200, json=[CLIENT])
        if req.url.path.endswith("/commandes"):
            return httpx.Response(200, json=[{"id": "1", "client_id": "42", "date": "2026-10-01T08:00:00",
                                               "lignes": [{"produit_code": "A", "quantite": 2, "prix_unitaire_ht": 3}]}])
        if req.url.path.endswith("/produits"):
            return httpx.Response(200, json=[{"code": "A", "libelle": "A", "famille": "frais", "prix_unitaire_ht": 3}])
        return httpx.Response(200, json=[{"id": "L1", "produit_code": "A", "quantite": 5,
                                          "dlc": "2026-10-25", "date_reception": "2026-10-20"}])

    source = faire_source(gestionnaire, requetes)
    assert source.get_clients()[0].nom == "Chez Test"
    commandes = source.get_order_history("42")
    assert commandes[0].montant_ht == 6
    assert source.get_products()[0].code == "A"
    assert source.get_stock()[0].dlc.isoformat() == "2026-10-25"

    assert {r.method for r in requetes} == {"GET"}  # jamais d'écriture
    assert all(r.headers["Authorization"] == "Bearer secret" for r in requetes)
    assert requetes[1].url.params["client_id"] == "42"
    assert "depuis" not in requetes[1].url.params  # paramètres vides non envoyés


def test_pagination():
    requetes = []

    def gestionnaire(req):
        if "page=2" in str(req.url):
            return httpx.Response(200, json={"items": [{**CLIENT, "id": "2"}], "next": None})
        return httpx.Response(200, json={"items": [CLIENT], "next": "/clients?page=2"})

    assert [c.id for c in faire_source(gestionnaire, requetes).get_clients()] == ["42", "2"]


def test_erreurs():
    source = faire_source(lambda req: httpx.Response(404), [])
    with pytest.raises(ClientIntrouvable):
        source.get_client("1")
    source = faire_source(lambda req: httpx.Response(500, text="panne"), [])
    with pytest.raises(DataSourceError):
        source.get_products()


def test_configuration_obligatoire(monkeypatch):
    monkeypatch.delenv("DATAHUB_URL", raising=False)
    monkeypatch.delenv("DATAHUB_TOKEN", raising=False)
    with pytest.raises(DataSourceError):
        get_datasource("http")
    monkeypatch.setenv("DATAHUB_URL", "https://datahub.test")
    with pytest.raises(DataSourceError):
        get_datasource("http")
    monkeypatch.setenv("DATAHUB_TOKEN", "x")
    assert isinstance(get_datasource("http"), HttpDataSource)


def test_aucune_methode_d_ecriture():
    """Garde-fou : le client n'expose aucune méthode d'écriture."""
    interdits = ("post", "put", "patch", "delete", "create", "update", "write", "save")
    publiques = [m for m in dir(HttpDataSource) if not m.startswith("__")]
    assert not [m for m in publiques if any(m.lower().lstrip("_").startswith(i) for i in interdits)]
