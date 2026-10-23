"""Simulateur du datahub, contrat d'interface et chemin `DATASOURCE=http` de bout en bout."""

from __future__ import annotations

import time

import pytest
from fastapi.testclient import TestClient

from copilote.application import creer_application
from copilote.comptes import DepotUtilisateursMemoire
from copilote.config import Config, ConfigDatahub, ConfigSecurite, ModeLLM, TypeSource
from copilote.datahub import SourceEnCache, creer_source
from copilote.datahub.http import HttpDataSource
from copilote.datahub.mock import MockDataSource
from copilote.datahub.simulateur import charger_donnees, creer_simulateur
from copilote.domaine import ClientIntrouvable, ErreurSourceDonnees
from copilote.journal import DepotMemoire
from scripts import exporter_contrat_datahub

from .conftest import AUJOURD_HUI, JETON_SIMULATEUR, SECRET_TEST

ENTETE = {"Authorization": f"Bearer {JETON_SIMULATEUR}"}


@pytest.fixture(scope="module")
def simulateur() -> TestClient:
    return TestClient(creer_simulateur(jeton=JETON_SIMULATEUR))


def source_http(url: str, jeton: str = JETON_SIMULATEUR) -> HttpDataSource:
    return HttpDataSource(ConfigDatahub(url=url, token=jeton, date_reference=AUJOURD_HUI))


# --------------------------------------------------------------------------- simulateur


@pytest.mark.parametrize("entetes", [{}, {"Authorization": "Bearer mauvais"}, {"Authorization": JETON_SIMULATEUR}])
def test_jeton_obligatoire(simulateur: TestClient, entetes: dict[str, str]):
    assert simulateur.get("/clients", headers=entetes).status_code == 401
    assert simulateur.get("/clients", headers=ENTETE).status_code == 200


def test_pagination_avec_filtres_conserves(simulateur: TestClient, mock_source: MockDataSource):
    reponse = simulateur.get("/commandes", params={"client_id": "C001", "taille": 5}, headers=ENTETE).json()
    assert len(reponse["items"]) == 5
    assert reponse["next"] == "/commandes?client_id=C001&page=2&taille=5"
    total, suivant = len(reponse["items"]), reponse["next"]
    while suivant:
        page = simulateur.get(suivant, headers=ENTETE).json()
        assert all(c["client_id"] == "C001" for c in page["items"])
        total, suivant = total + len(page["items"]), page["next"]
    assert total == len(mock_source.get_order_history("C001"))


def test_filtre_depuis_et_client_inconnu(simulateur: TestClient):
    reponse = simulateur.get("/commandes", params={"depuis": "2026-10-20", "taille": 1000}, headers=ENTETE).json()
    assert reponse["items"] and all(c["date"] >= "2026-10-20" for c in reponse["items"])
    assert simulateur.get("/clients/C999", headers=ENTETE).status_code == 404
    assert simulateur.get("/clients", params={"taille": 0}, headers=ENTETE).status_code == 422


def test_latence_simulee():
    lent = TestClient(creer_simulateur(jeton="j", latence_ms=40))
    debut = time.perf_counter()
    assert lent.get("/produits", headers={"Authorization": "Bearer j"}).status_code == 200
    assert time.perf_counter() - debut >= 0.04


def test_anomalies_injectees_de_facon_deterministe(mock_source: MockDataSource):
    propres = charger_donnees(mock_source, anomalies=False)
    defectueuses = charger_donnees(mock_source, anomalies=True)
    assert len(defectueuses.clients) == len(propres.clients) + 1  # un doublon
    assert len(defectueuses.produits) == len(propres.produits) + 1  # un doublon
    assert len(defectueuses.commandes) == len(propres.commandes) + 5
    assert len(defectueuses.lots) == len(propres.lots) + 2
    assert charger_donnees(mock_source, anomalies=True) == defectueuses


def test_contrat_exporte_a_jour():
    """`docs/contrat-datahub.json` correspond au simulateur (sinon : make contrat)."""
    assert exporter_contrat_datahub.SORTIE.read_text(encoding="utf-8") == exporter_contrat_datahub.generer()


def test_contrat_documente_les_ressources_lues_par_le_copilote():
    schema = creer_simulateur().openapi()
    assert set(schema["paths"]) == {"/clients", "/clients/{client_id}", "/commandes", "/produits", "/stock/lots"}
    assert all(set(operations) == {"get"} for operations in schema["paths"].values())  # lecture seule
    commande = schema["components"]["schemas"]["CommandeContrat"]
    assert set(commande["required"]) == {"id", "client_id", "date", "lignes"}


# --------------------------------------------------------------------------- bout en bout


def test_http_restitue_exactement_les_donnees_du_mock(url_simulateur: str, mock_source: MockDataSource):
    """HttpDataSource → réseau → simulateur : pagination, jeton et correspondance des champs."""
    source = source_http(url_simulateur)
    assert source.get_clients() == mock_source.get_clients()
    assert source.get_products() == mock_source.get_products()
    assert source.get_stock() == mock_source.get_stock()
    assert source.get_order_history() == mock_source.get_order_history()  # 1 300 commandes, 7 pages
    assert source.get_order_history("C007") == mock_source.get_order_history("C007")
    assert source.get_client("C003") == mock_source.get_client("C003")
    with pytest.raises(ClientIntrouvable):
        source.get_client("C999")


def test_fiche_identique_via_http_et_via_le_mock(url_simulateur: str, mock_source: MockDataSource, horloge):
    def application(source):
        return creer_application(
            Config(mode_llm=ModeLLM.SIMULE, securite=ConfigSecurite(secret_session=SECRET_TEST)),
            source=source,
            depot_journal=DepotMemoire(),
            horloge=horloge,
            depot_utilisateurs=DepotUtilisateursMemoire(),
        )

    par_http = application(SourceEnCache(source_http(url_simulateur), 60))
    par_mock = application(mock_source)
    for client_id in ("C001", "C014", "C027"):
        fiche_http = par_http.fiches.generer(client_id).model_dump(exclude={"trace"})
        assert fiche_http == par_mock.fiches.generer(client_id).model_dump(exclude={"trace"})
    assert par_http.pilotage.file_appels() == par_mock.pilotage.file_appels()


def test_jeton_refuse_message_explicite(url_simulateur: str):
    with pytest.raises(ErreurSourceDonnees, match="DATAHUB_TOKEN"):
        source_http(url_simulateur, jeton="mauvais").get_clients()


def test_configuration_http_complete(url_simulateur: str):
    env = {
        "DATASOURCE": "http",
        "DATAHUB_URL": url_simulateur,
        "DATAHUB_TOKEN": JETON_SIMULATEUR,
        "DATAHUB_DATE_REFERENCE": "2026-10-23",
    }
    config = Config.depuis_environnement(env)
    assert config.source is TypeSource.HTTP and config.datahub.date_reference == AUJOURD_HUI
    source = creer_source(config)
    assert source.date_du_jour() == AUJOURD_HUI and len(source.get_clients()) == 30
