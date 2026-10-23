"""Comptes, mots de passe, sessions, droits d'accès et sécurité HTTP."""

from __future__ import annotations

from datetime import datetime, timedelta
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from copilote import admin
from copilote.api import creer_app
from copilote.application import creer_application
from copilote.comptes import (
    AuthentificationRefusee,
    DepotUtilisateursMemoire,
    DepotUtilisateursSQLite,
    MotDePasseInvalide,
    Permission,
    Role,
    ServiceComptes,
    SignataireSessions,
    TropDeTentatives,
    Utilisateur,
    UtilisateurExistant,
    UtilisateurIntrouvable,
    mots_de_passe,
)
from copilote.config import Config, ConfigSecurite, ModeLLM
from copilote.journal import DepotMemoire
from scripts.sauvegarder import purger, sauvegarder
from tests.conftest import MOT_DE_PASSE_TEST, SECRET_TEST

MAINTENANT = datetime(2026, 10, 23, 9, 0)


# ------------------------------------------------------------------- mots de passe


def test_hachage_et_verification():
    hachage = mots_de_passe.hacher("Correct-Horse-42")
    assert hachage.startswith("scrypt$") and "Correct" not in hachage
    assert mots_de_passe.verifier("Correct-Horse-42", hachage)
    assert not mots_de_passe.verifier("correct-horse-42", hachage)
    assert hachage != mots_de_passe.hacher("Correct-Horse-42")  # sel aléatoire
    assert not mots_de_passe.verifier("x", "pas$un$hachage")


@pytest.mark.parametrize("faible", ["court", "1234567890123", " espaces-autour ", ""])
def test_politique_de_mot_de_passe(faible):
    with pytest.raises(MotDePasseInvalide):
        mots_de_passe.hacher(faible)


def test_mot_de_passe_genere_conforme():
    mots_de_passe.verifier_politique(mots_de_passe.generer_mot_de_passe())


# ------------------------------------------------------------------- sessions


def test_jeton_signe_infalsifiable_et_limite_dans_le_temps():
    signataire = SignataireSessions(SECRET_TEST, timedelta(hours=12))
    jeton = signataire.emettre("julie", "hachage", MAINTENANT)
    session = signataire.verifier(jeton, MAINTENANT + timedelta(hours=1))
    assert session is not None and session.identifiant == "julie"
    assert signataire.verifier(jeton, MAINTENANT + timedelta(hours=13)) is None  # expiré
    contenu, signature = jeton.split(".")
    assert signataire.verifier(f"{contenu}x.{signature}", MAINTENANT) is None  # contenu modifié
    assert signataire.verifier(f"{contenu}.{signature[:-2]}AA", MAINTENANT) is None  # signature modifiée
    autre = SignataireSessions("un-autre-secret-de-session-tres-long-0000", timedelta(hours=12))
    assert autre.verifier(jeton, MAINTENANT) is None  # mauvais secret
    assert signataire.verifier("n'importe quoi", MAINTENANT) is None


def test_secret_trop_court_refuse():
    with pytest.raises(ValueError):
        SignataireSessions("court", timedelta(hours=1))


# ------------------------------------------------------------------- service de comptes


@pytest.fixture
def service(depot_utilisateurs) -> ServiceComptes:
    temps = [0.0]
    service = ServiceComptes(
        depot_utilisateurs, SignataireSessions(SECRET_TEST, timedelta(hours=12)), lambda: MAINTENANT, lambda: temps[0]
    )
    service.temps = temps  # type: ignore[attr-defined]
    return service


def test_connexion_et_session(service):
    utilisateur, jeton = service.connecter(" JULIE ", MOT_DE_PASSE_TEST)  # identifiant normalisé
    assert utilisateur.nom_affiche == "Julie Moreau"
    assert service.utilisateur_de_session(jeton) == utilisateur


def test_connexion_refusee_sans_indice(service):
    with pytest.raises(AuthentificationRefusee, match="Identifiant ou mot de passe incorrect"):
        service.connecter("julie", "mauvais-mot-de-passe")
    with pytest.raises(AuthentificationRefusee, match="Identifiant ou mot de passe incorrect"):
        service.connecter("inconnu", MOT_DE_PASSE_TEST)


def test_blocage_apres_cinq_echecs(service):
    for _ in range(5):
        with pytest.raises(AuthentificationRefusee):
            service.connecter("julie", "mauvais-mot-de-passe")
    with pytest.raises(TropDeTentatives):
        service.connecter("julie", MOT_DE_PASSE_TEST)  # même le bon mot de passe est bloqué
    service.temps[0] = 61  # une minute plus tard
    service.connecter("julie", MOT_DE_PASSE_TEST)


def test_desactivation_et_changement_de_mot_de_passe_ferment_les_sessions(service):
    _, jeton = service.connecter("julie", MOT_DE_PASSE_TEST)
    service.changer_mot_de_passe("julie", "Nouveau-Mot-De-Passe-1")
    assert service.utilisateur_de_session(jeton) is None
    _, jeton = service.connecter("julie", "Nouveau-Mot-De-Passe-1")
    service.activer("julie", False)
    assert service.utilisateur_de_session(jeton) is None
    with pytest.raises(AuthentificationRefusee):
        service.connecter("julie", "Nouveau-Mot-De-Passe-1")


def test_creation_et_erreurs(service):
    utilisateur = service.creer("karim.bensaid", "Karim Bensaïd", Role.TELEVENDEUR, "Mot-De-Passe-Solide")
    assert utilisateur.cree_le == MAINTENANT
    with pytest.raises(UtilisateurExistant):
        service.creer("karim.bensaid", "Doublon", Role.TELEVENDEUR, "Mot-De-Passe-Solide")
    with pytest.raises(UtilisateurIntrouvable):
        service.changer_mot_de_passe("personne", "Mot-De-Passe-Solide")
    with pytest.raises(ValueError):
        service.creer("Identifiant Invalide!", "x", Role.TELEVENDEUR, "Mot-De-Passe-Solide")


def test_permissions():
    cree_le = MAINTENANT
    televendeur = Utilisateur(identifiant="t1", nom_affiche="T", role=Role.TELEVENDEUR, cree_le=cree_le)
    responsable = Utilisateur(identifiant="r1", nom_affiche="R", role=Role.RESPONSABLE, cree_le=cree_le)
    assert not any(televendeur.peut(p) for p in Permission)
    assert all(responsable.peut(p) for p in Permission)
    assert not responsable.model_copy(update={"actif": False}).peut(Permission.UTILISER_LE_LABO)


def test_depot_sqlite(tmp_path: Path, hachage_test):
    depot = DepotUtilisateursSQLite(tmp_path / "comptes.sqlite3")
    utilisateur = Utilisateur(
        identifiant="julie", nom_affiche="Julie Moreau", role=Role.TELEVENDEUR, cree_le=MAINTENANT
    )
    depot.creer(utilisateur, hachage_test)
    with pytest.raises(UtilisateurExistant):
        depot.creer(utilisateur, hachage_test)
    compte = DepotUtilisateursSQLite(tmp_path / "comptes.sqlite3").obtenir("julie")
    assert compte is not None and compte.utilisateur == utilisateur and compte.hachage == hachage_test
    depot.modifier_activite("julie", False)
    assert depot.lister()[0].actif is False
    with pytest.raises(UtilisateurIntrouvable):
        depot.modifier_mot_de_passe("personne", "x")


# ------------------------------------------------------------------- API : authentification et droits


@pytest.mark.parametrize(
    "url", ["/session", "/clients", "/clients/C010/fiche", "/appels/file", "/statistiques", "/stock/plan-ecoulement"]
)
def test_routes_protegees(application, url):
    assert TestClient(creer_app(application)).get(url).status_code == 401


def test_interface_et_sante_publiques(application):
    client = TestClient(creer_app(application))
    assert client.get("/").status_code == 200 and client.get("/sante").status_code == 200


def test_cookie_de_session_securise(application):
    client = TestClient(creer_app(application))
    reponse = client.post("/auth/connexion", json={"identifiant": "julie", "mot_de_passe": MOT_DE_PASSE_TEST})
    cookie = reponse.headers["set-cookie"]
    assert "copilote_session=" in cookie and "HttpOnly" in cookie and "SameSite=strict" in cookie
    assert "Secure" not in cookie  # en développement (HTTP) ; activé par COOKIE_SECURISE en production
    assert client.get("/session").json()["utilisateur"]["role"] == "televendeur"
    assert client.post("/auth/deconnexion").status_code == 204
    assert client.get("/session").status_code == 401


def test_cookie_secure_en_production(mock_source, depot_utilisateurs):
    config = Config(securite=ConfigSecurite(secret_session=SECRET_TEST, cookie_securise=True))
    app = creer_application(
        config, source=mock_source, depot_journal=DepotMemoire(), depot_utilisateurs=depot_utilisateurs
    )
    reponse = TestClient(creer_app(app), base_url="https://testserver").post(
        "/auth/connexion", json={"identifiant": "julie", "mot_de_passe": MOT_DE_PASSE_TEST}
    )
    assert "Secure" in reponse.headers["set-cookie"]


def test_mauvais_mot_de_passe_et_blocage_http(application):
    client = TestClient(creer_app(application))
    for _ in range(5):
        assert client.post("/auth/connexion", json={"identifiant": "julie", "mot_de_passe": "faux"}).status_code == 401
    bloque = client.post("/auth/connexion", json={"identifiant": "julie", "mot_de_passe": MOT_DE_PASSE_TEST})
    assert bloque.status_code == 429


def test_televendeur_ne_voit_que_sa_file(api_televendeur):
    appels = api_televendeur.get("/appels/file", params={"televendeur": "Karim Bensaïd"}).json()["appels"]
    assert appels and {a["client"]["commercial"] for a in appels} == {"Julie Moreau"}


def test_labo_reserve_aux_responsables(api_televendeur, api):
    assert api_televendeur.get("/labo/agent").status_code == 403
    assert api.get("/labo/agent").status_code == 200


def test_compte_rendu_attribue_a_l_utilisateur_connecte(api_televendeur, api):
    saisie = {"client_id": "C002", "issue": "injoignable"}
    corps = api_televendeur.post("/comptes-rendus", json=saisie).json()
    assert corps["compte_rendu"]["televendeur"] == "Julie Moreau"
    usurpation = api_televendeur.post("/comptes-rendus", json={**saisie, "televendeur": "Karim Bensaïd"})
    assert usurpation.status_code == 422  # champ refusé : l'auteur ne se choisit pas
    api.post("/comptes-rendus", json={"client_id": "C003", "issue": "injoignable"})
    assert api_televendeur.get("/statistiques").json()["nb_appels"] == 1  # ses propres résultats
    assert api.get("/statistiques").json()["nb_appels"] == 2  # vue globale


def test_en_tetes_de_securite(api):
    entetes = api.get("/clients").headers
    assert entetes["x-content-type-options"] == "nosniff"
    assert entetes["x-frame-options"] == "DENY"
    assert "default-src 'self'" in entetes["content-security-policy"]


def test_ecriture_non_json_refusee(api):
    reponse = api.post("/comptes-rendus", content="client_id=C001", headers={"Content-Type": "text/plain"})
    assert reponse.status_code == 415


def test_documentation_desactivable(mock_source, depot_utilisateurs):
    config = Config(securite=ConfigSecurite(secret_session=SECRET_TEST, documentation_api=False))
    app = creer_application(
        config, source=mock_source, depot_journal=DepotMemoire(), depot_utilisateurs=depot_utilisateurs
    )
    assert TestClient(creer_app(app)).get("/docs").status_code == 404


def test_mode_sans_authentification(mock_source, depot_utilisateurs):
    config = Config(mode_llm=ModeLLM.REPLI, securite=ConfigSecurite(authentification=False, secret_session=SECRET_TEST))
    app = creer_application(
        config, source=mock_source, depot_journal=DepotMemoire(), depot_utilisateurs=depot_utilisateurs
    )
    client = TestClient(creer_app(app))
    assert client.get("/session").json()["utilisateur"]["identifiant"] == "developpement"
    assert client.get("/labo/agent").status_code == 200


# ------------------------------------------------------------------- administration et sauvegarde


def test_commandes_d_administration(tmp_path, monkeypatch, capsys):
    monkeypatch.setenv("DOSSIER_DONNEES", str(tmp_path))
    monkeypatch.setenv("COPILOTE_MOT_DE_PASSE", "Mot-De-Passe-Solide")
    assert admin.main(["creer", "sophie", "--nom", "Sophie Lefèvre", "--role", "responsable"]) == 0
    assert admin.main(["creer", "sophie", "--nom", "Doublon"]) == 1
    assert admin.main(["desactiver", "sophie"]) == 0
    assert admin.main(["demo"]) == 0
    sortie = capsys.readouterr().out
    assert "karim.bensaid" in sortie and "responsable" in sortie
    admin.main(["lister"])
    liste = capsys.readouterr().out
    assert "sophie" in liste and "désactivé" in liste and "julie.moreau" in liste
    assert admin.identifiant_depuis_nom("Karim Bensaïd") == "karim.bensaid"


def test_sauvegarde_et_rotation(tmp_path: Path):
    base = tmp_path / "journal.sqlite3"
    DepotUtilisateursSQLite(base)  # crée une base SQLite valide
    destination = tmp_path / "sauvegardes"
    destination.mkdir()
    for i in range(4):
        assert sauvegarder(base, destination, f"2026102{i}-000000") is not None
    supprimees = purger(destination, "journal", garder=2)
    assert len(supprimees) == 2 and len(list(destination.iterdir())) == 2
    assert sauvegarder(tmp_path / "absente.sqlite3", destination, "x") is None


def test_service_sans_signataire_pour_l_administration():
    service = ServiceComptes(DepotUtilisateursMemoire())
    service.creer("admin", "Admin", Role.ADMIN, "Mot-De-Passe-Solide")
    with pytest.raises(Exception, match="Sessions indisponibles"):
        service.connecter("admin", "Mot-De-Passe-Solide")
