"""Sources de données : mock, client HTTP (sans réseau), cache, configuration, générateur."""

from __future__ import annotations

import json
from datetime import timedelta
from pathlib import Path

import httpx
import pytest

from copilote.config import Config, ConfigDatahub, ModeLLM, TypeSource
from copilote.datahub import SourceEnCache, creer_source
from copilote.datahub.http import HttpDataSource
from copilote.datahub.mock import CHEMIN_PAR_DEFAUT, MockDataSource
from copilote.domaine import ClientIntrouvable, ErreurConfiguration, ErreurSourceDonnees, Famille
from copilote.fournisseurs import ConfigFournisseur
from scripts.generer_donnees_mock import generer

# --------------------------------------------------------------------------- mock


def test_volumes_du_mock(mock_source):
    assert len(mock_source.get_clients()) == 30
    produits = mock_source.get_products()
    assert len(produits) == 80
    assert {p.famille for p in produits} == {Famille.FRAIS, Famille.SURGELE}
    assert len({c.type for c in mock_source.get_clients()}) >= 6


def test_historique_sur_six_mois_et_trie(mock_source):
    commandes = mock_source.get_order_history()
    assert commandes == sorted(commandes, key=lambda c: (c.date, c.id))
    assert timedelta(days=170) <= commandes[-1].date - commandes[0].date <= timedelta(days=185)
    assert commandes[-1].date < mock_source.date_du_jour()


def test_coherence_referentielle(mock_source):
    codes = {p.code for p in mock_source.get_products()}
    clients = {c.id for c in mock_source.get_clients()}
    for cmd in mock_source.get_order_history():
        assert cmd.client_id in clients
        assert cmd.codes_produits <= codes
    assert all(l.produit_code in codes for l in mock_source.get_stock())


def test_filtres_et_erreurs(mock_source):
    depuis = mock_source.date_du_jour() - timedelta(days=30)
    commandes = mock_source.get_order_history("C001", depuis=depuis)
    assert commandes and all(c.client_id == "C001" and c.date >= depuis for c in commandes)
    with pytest.raises(ClientIntrouvable):
        mock_source.get_client("C999")
    with pytest.raises(ClientIntrouvable):
        mock_source.get_order_history("C999")


def test_fichier_mock_absent_ou_invalide(tmp_path: Path):
    with pytest.raises(ErreurSourceDonnees):
        MockDataSource(tmp_path / "absent.json")
    invalide = tmp_path / "invalide.json"
    invalide.write_text('{"meta": {}}', encoding="utf-8")
    with pytest.raises(ErreurSourceDonnees):
        MockDataSource(invalide)


def test_fichier_a_jour_avec_le_generateur():
    """Le JSON versionné correspond exactement à la sortie du script seedé."""
    assert json.loads(CHEMIN_PAR_DEFAUT.read_text(encoding="utf-8")) == generer().vers_json()


def test_generateur_deterministe():
    assert generer(7).vers_json() == generer(7).vers_json()
    assert generer(7).vers_json() != generer(8).vers_json()


# --------------------------------------------------------------------------- http

CLIENT_JSON = {
    "id": "42",
    "nom": "Chez Test",
    "type": "Restaurant",
    "ville": "Lyon",
    "contact": "M. X",
    "telephone": "04",
    "commercial": "Julie",
}


def source_http(gestionnaire, requetes: list[httpx.Request]) -> HttpDataSource:
    def transport(requete: httpx.Request) -> httpx.Response:
        requetes.append(requete)
        return gestionnaire(requete)

    return HttpDataSource(ConfigDatahub(url="https://datahub.test/api", token="secret"), httpx.MockTransport(transport))


def test_http_lecture_seule_et_correspondance():
    requetes: list[httpx.Request] = []

    def gestionnaire(req: httpx.Request) -> httpx.Response:
        chemin = req.url.path
        if chemin.endswith("/clients"):
            return httpx.Response(200, json=[CLIENT_JSON])
        if chemin.endswith("/commandes"):
            return httpx.Response(
                200,
                json=[
                    {
                        "id": "1",
                        "client_id": "42",
                        "date": "2026-10-01T08:00:00",
                        "lignes": [{"produit_code": "A", "quantite": 2, "prix_unitaire_ht": 3}],
                    }
                ],
            )
        if chemin.endswith("/produits"):
            return httpx.Response(200, json=[{"code": "A", "libelle": "A", "famille": "frais", "prix_unitaire_ht": 3}])
        return httpx.Response(
            200,
            json=[
                {"id": "L1", "produit_code": "A", "quantite": 5, "dlc": "2026-10-25", "date_reception": "2026-10-20"}
            ],
        )

    source = source_http(gestionnaire, requetes)
    assert source.get_clients()[0].nom == "Chez Test"
    assert source.get_order_history("42")[0].montant_ht == 6
    assert source.get_products()[0].famille is Famille.FRAIS
    assert source.get_stock()[0].dlc.isoformat() == "2026-10-25"
    assert {r.method for r in requetes} == {"GET"}  # jamais d'écriture
    assert all(r.headers["Authorization"] == "Bearer secret" for r in requetes)
    assert requetes[1].url.params["client_id"] == "42"
    assert "depuis" not in requetes[1].url.params


def test_http_pagination():
    def gestionnaire(req: httpx.Request) -> httpx.Response:
        if "page=2" in str(req.url):
            return httpx.Response(200, json={"items": [{**CLIENT_JSON, "id": "2"}], "next": None})
        return httpx.Response(200, json={"items": [CLIENT_JSON], "next": "/clients?page=2"})

    assert [c.id for c in source_http(gestionnaire, []).get_clients()] == ["42", "2"]


def test_http_erreurs():
    with pytest.raises(ClientIntrouvable):
        source_http(lambda _r: httpx.Response(404), []).get_client("1")
    with pytest.raises(ErreurSourceDonnees):
        source_http(lambda _r: httpx.Response(500, text="panne"), []).get_products()
    with pytest.raises(ErreurSourceDonnees):  # champ obligatoire manquant
        source_http(lambda _r: httpx.Response(200, json=[{"id": "1"}]), []).get_clients()


def test_http_reponses_non_conformes_signalees_avec_l_element_fautif():
    with pytest.raises(ErreurSourceDonnees, match="Réponse non JSON"):
        source_http(lambda _r: httpx.Response(200, text="<html>maintenance</html>"), []).get_clients()
    with pytest.raises(ErreurSourceDonnees, match="DATAHUB_TOKEN"):
        source_http(lambda _r: httpx.Response(403), []).get_clients()
    famille_inconnue = [{"code": "Z1", "libelle": "Z", "famille": "ambiant", "prix_unitaire_ht": 1}]
    with pytest.raises(ErreurSourceDonnees, match=r"Élément non conforme dans /produits \(Z1\)"):
        source_http(lambda _r: httpx.Response(200, json=famille_inconnue), []).get_products()
    prix_negatif = [{"code": "Z2", "libelle": "Z", "famille": "frais", "prix_unitaire_ht": -1}]
    with pytest.raises(ErreurSourceDonnees, match=r"\(Z2\)"):
        source_http(lambda _r: httpx.Response(200, json=prix_negatif), []).get_products()


def test_http_lignes_annulees_ignorees():
    commande = {
        "id": "1",
        "client_id": "42",
        "date": "2026-10-01",
        "lignes": [
            {"produit_code": "A", "quantite": 2, "prix_unitaire_ht": 3},
            {"produit_code": "B", "quantite": 0, "prix_unitaire_ht": 3},  # ligne annulée
            {"produit_code": "C", "quantite": -1, "prix_unitaire_ht": 3},  # avoir
        ],
    }
    lue = source_http(lambda _r: httpx.Response(200, json=[commande]), []).get_order_history()[0]
    assert [ligne.produit_code for ligne in lue.lignes] == ["A"]


def test_http_configuration_obligatoire():
    with pytest.raises(ErreurConfiguration):
        HttpDataSource(ConfigDatahub())
    with pytest.raises(ErreurConfiguration):
        HttpDataSource(ConfigDatahub(url="https://x"))


def test_http_aucune_methode_d_ecriture():
    interdits = ("post", "put", "patch", "delete", "create", "update", "write", "save")
    publiques = [m for m in dir(HttpDataSource) if not m.startswith("__")]
    assert not [m for m in publiques if any(m.lower().lstrip("_").startswith(i) for i in interdits)]


# --------------------------------------------------------------------------- cache


def test_cache_memorise_puis_expire(source_simple):
    appels = 0
    original = source_simple.get_products

    def compter():
        nonlocal appels
        appels += 1
        return original()

    source_simple.get_products = compter
    temps = [0.0]
    cache = SourceEnCache(source_simple, duree_secondes=60, horloge=lambda: temps[0])
    cache.get_products()
    cache.get_products()
    assert appels == 1
    temps[0] = 61
    cache.get_products()
    assert appels == 2
    cache.vider()
    cache.get_products()
    assert appels == 3


# --------------------------------------------------------------------------- configuration


def test_configuration_depuis_environnement():
    config = Config.depuis_environnement(
        {
            "DATASOURCE": "HTTP",
            "LLM_MODE": "repli",
            "ANTHROPIC_API_KEY": "x",
            "DATAHUB_URL": "https://d",
            "DATAHUB_TOKEN": "t",
            "CACHE_SECONDES": "10",
        }
    )
    assert config.source is TypeSource.HTTP
    assert config.mode_llm is ModeLLM.REPLI
    assert config.fournisseurs_utilisables == [ModeLLM.ANTHROPIC]
    assert config.datahub.url == "https://d"
    assert config.duree_cache_secondes == 10
    assert isinstance(creer_source(config), SourceEnCache)


def test_mode_auto():
    claude = {ModeLLM.ANTHROPIC: ConfigFournisseur.pour(ModeLLM.ANTHROPIC, cle_api="x")}
    assert Config(fournisseurs=claude).mode_llm_effectif is ModeLLM.ANTHROPIC
    assert Config().mode_llm_effectif is ModeLLM.SIMULE
    assert Config(mode_llm=ModeLLM.REPLI, fournisseurs=claude).mode_llm_effectif is ModeLLM.REPLI


def test_configuration_invalide():
    with pytest.raises(ErreurConfiguration):
        Config.depuis_environnement({"DATASOURCE": "ftp"})
    with pytest.raises(ErreurConfiguration):
        Config.depuis_environnement({"CACHE_SECONDES": "beaucoup"})
