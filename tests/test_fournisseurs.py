"""Multi-fournisseur : catalogue, configuration, adaptateur « Chat Completions » (OpenAI, Mistral, Gemini, local)."""

from __future__ import annotations

import json
from collections.abc import Iterator
from datetime import date

import httpx2  # transport du SDK openai 3.x
import openai
import pytest

from copilote.agent import RedacteurIA, creer_boite_outils
from copilote.agent.llm import (
    FournisseurChatCompletions,
    FournisseurClaude,
    ParametresChatCompletions,
    creer_fournisseur,
)
from copilote.agent.llm.chat_completions import CLE_ARGUMENTS_INVALIDES
from copilote.agent.llm.simulateur_openai import creer_simulateur_openai
from copilote.agent.llm.types import Arret, DefinitionOutil, ErreurFournisseurLLM, ResultatOutil
from copilote.application import Application, creer_application, fournisseurs_par_defaut, tarifs_des_redacteurs
from copilote.comptes import DepotUtilisateursMemoire
from copilote.config import Config, ConfigSecurite, ModeLLM
from copilote.domaine import ErreurConfiguration
from copilote.evaluation import DepotEvaluationsMemoire
from copilote.fiche import ModeFiche
from copilote.fournisseurs import PROFILS, TARIFS_PUBLICS, ConfigFournisseur, Protocole, Tarif
from copilote.journal import DepotMemoire
from tests.test_agent import REDACTION

from .conftest import SECRET_TEST, client_connecte, servir


def completion(message: dict, fin: str = "tool_calls", modele: str = "mistral-test") -> dict:
    """Réponse de l'API Chat Completions."""
    return {
        "id": "cmpl-1",
        "object": "chat.completion",
        "created": 1,
        "model": modele,
        "choices": [{"index": 0, "finish_reason": fin, "message": {"role": "assistant", **message}}],
        "usage": {"prompt_tokens": 900, "completion_tokens": 120, "total_tokens": 1020},
    }


def appel(identifiant: str, nom: str, arguments: object) -> dict:
    texte = arguments if isinstance(arguments, str) else json.dumps(arguments)
    return {"id": identifiant, "type": "function", "function": {"name": nom, "arguments": texte}}


def client_openai(reponses: list[httpx2.Response], requetes: list[httpx2.Request]) -> openai.OpenAI:
    def transport(requete: httpx2.Request) -> httpx2.Response:
        requetes.append(requete)
        return reponses.pop(0)

    return openai.OpenAI(
        api_key="test",
        base_url="https://api.mistral.ai/v1",
        http_client=httpx2.Client(transport=httpx2.MockTransport(transport)),
        max_retries=0,
    )


def mistral(client: openai.OpenAI, **options: object) -> FournisseurChatCompletions:
    parametres = ParametresChatCompletions(nom="mistral", libelle="Mistral AI", modele="mistral-test", **options)  # type: ignore[arg-type]
    return FournisseurChatCompletions(parametres, client)


# --------------------------------------------------------------------------- adaptateur Chat Completions


def test_boucle_complete_via_le_sdk_openai(ref_simple):
    """Appels d'outils parallèles, résultats renvoyés un par un, puis soumission de la fiche."""
    requetes: list[httpx2.Request] = []
    signature = {"google": {"thought_signature": "abc"}}  # champ propre à un fournisseur, à conserver
    reponses = [
        httpx2.Response(
            200,
            json=completion(
                {
                    "content": "Je consulte les données.",
                    "tool_calls": [
                        {**appel("call_1", "historique_client", {"client_id": "R1"}), "extra_content": signature},
                        appel("call_2", "stock_a_ecouler", {"client_id": "R1"}),
                    ],
                }
            ),
        ),
        httpx2.Response(
            200, json=completion({"content": None, "tool_calls": [appel("call_3", "soumettre_fiche", REDACTION)]})
        ),
    ]
    resultat = RedacteurIA(mistral(client_openai(reponses, requetes))).rediger(
        ref_simple.client("R1"), date(2026, 10, 23), creer_boite_outils(ref_simple, "R1", [])
    )

    assert resultat.redaction.stock_a_ecouler[0].code == "P1"
    premiere = json.loads(requetes[0].content)
    assert str(requetes[0].url) == "https://api.mistral.ai/v1/chat/completions"
    assert premiere["model"] == "mistral-test" and premiere["tool_choice"] == "auto"
    assert premiere["max_tokens"] == 8192 and "max_completion_tokens" not in premiere
    assert [m["role"] for m in premiere["messages"]] == ["system", "user"]
    outils = {o["function"]["name"]: o for o in premiere["tools"]}
    assert set(outils) >= {"historique_client", "soumettre_fiche"} and all(
        o["type"] == "function" for o in outils.values()
    )
    assert "strict" not in outils["soumettre_fiche"]["function"]  # désactivé par défaut hors API OpenAI
    seconde = json.loads(requetes[1].content)
    assert [m["role"] for m in seconde["messages"]] == ["system", "user", "assistant", "tool", "tool"]
    assistant = seconde["messages"][2]
    assert assistant["tool_calls"][0]["extra_content"] == signature  # renvoyé intact
    assert [m["tool_call_id"] for m in seconde["messages"][3:]] == ["call_1", "call_2"]
    assert resultat.trace.fournisseur == "mistral" and resultat.trace.etapes[0].jetons_entree == 900


def test_parametres_specifiques_au_fournisseur():
    requetes: list[httpx2.Request] = []
    reponses = [httpx2.Response(200, json=completion({"content": "Bonjour"}, fin="stop"))]
    fournisseur = mistral(client_openai(reponses, requetes), limite_jetons="max_completion_tokens", outils_stricts=True)
    outil = DefinitionOutil(nom="o", description="d", schema_entree={"type": "object", "properties": {}})
    reponse = fournisseur.ouvrir_session("système", [outil], {}).envoyer("question")
    corps = json.loads(requetes[0].content)
    assert corps["max_completion_tokens"] == 8192 and "max_tokens" not in corps  # API OpenAI
    assert corps["tools"][0]["function"]["strict"] is True
    assert reponse.arret is Arret.FIN and reponse.textes == ["Bonjour"]


def test_traduction_des_reponses():
    session = mistral(
        client_openai(
            [
                httpx2.Response(200, json=completion({"content": "…"}, fin="length")),
                httpx2.Response(200, json=completion({"content": None, "refusal": "Non."}, fin="stop")),
                # Certains serveurs locaux répondent « stop » avec des appels d'outils et un JSON invalide.
                httpx2.Response(
                    200, json=completion({"tool_calls": [appel("c", "outil", "{pas du json")]}, fin="stop")
                ),
                httpx2.Response(200, json=completion({"tool_calls": [appel("d", "outil", "")]}, fin="tool_calls")),
            ],
            [],
        )
    ).ouvrir_session("s", [], {})
    assert session.envoyer("a").arret is Arret.LIMITE
    assert session.envoyer("b").arret is Arret.REFUS
    invalide = session.envoyer([ResultatOutil(appel_id="x", contenu="introuvable", est_erreur=True)])
    assert invalide.arret is Arret.OUTILS and invalide.appels[0].arguments == {CLE_ARGUMENTS_INVALIDES: "{pas du json"}
    assert session.envoyer("d").appels[0].arguments == {}


ERREUR_SIMPLE = {"message": "outil mal formé"}


@pytest.mark.parametrize(
    ("statut", "corps", "raison"),
    [
        (401, ERREUR_SIMPLE, "clé d'API Mistral AI refusée"),
        (403, ERREUR_SIMPLE, "clé d'API Mistral AI refusée"),
        (404, ERREUR_SIMPLE, "modèle « mistral-test » introuvable chez Mistral AI"),
        (429, ERREUR_SIMPLE, "limite d'utilisation de Mistral AI atteinte"),
        (400, ERREUR_SIMPLE, "requête refusée par Mistral AI : outil mal formé"),
        (400, {"error": ERREUR_SIMPLE}, "requête refusée par Mistral AI : outil mal formé"),
        # Réponse réelle de Gemini à une clé invalide (relevée le 23/10/2026) : un 400, dans une liste.
        (
            400,
            [{"error": {"code": 400, "message": "Please pass a valid API key", "status": "INVALID_ARGUMENT"}}],
            "clé d'API Mistral AI refusée",
        ),
        (503, ERREUR_SIMPLE, "erreur de Mistral AI (503)"),
    ],
)
def test_erreurs_http_traduites(statut: int, corps: object, raison: str):
    reponse = httpx2.Response(statut, json=corps)
    session = mistral(client_openai([reponse], [])).ouvrir_session("s", [], {})
    with pytest.raises(ErreurFournisseurLLM) as erreur:
        session.envoyer("question")
    assert erreur.value.raison == raison


def test_service_injoignable():
    def panne(_requete: httpx2.Request) -> httpx2.Response:
        raise httpx2.ConnectError("refusé")

    client = openai.OpenAI(
        api_key="t",
        base_url="http://localhost:11434/v1",
        http_client=httpx2.Client(transport=httpx2.MockTransport(panne)),
        max_retries=0,
    )
    with pytest.raises(ErreurFournisseurLLM, match="injoignable"):
        mistral(client).ouvrir_session("s", [], {}).envoyer("question")


def test_echec_du_fournisseur_bascule_en_repli(mock_source, horloge):
    """Clé refusée : la fiche est rédigée sans IA, avec un avertissement lisible."""
    fournisseur = mistral(client_openai([httpx2.Response(401, json={"message": "clé"})], []))
    app = creer_application(
        Config(mode_llm=ModeLLM.MISTRAL, securite=ConfigSecurite(secret_session=SECRET_TEST)),
        source=mock_source,
        depot_journal=DepotMemoire(),
        horloge=horloge,
        depot_utilisateurs=DepotUtilisateursMemoire(),
        depot_evaluations=DepotEvaluationsMemoire(),
        fournisseurs={ModeLLM.MISTRAL: fournisseur},
    )
    fiche = app.fiches.generer("C001")
    assert fiche.mode is ModeFiche.REPLI
    assert fiche.avertissement == "IA indisponible (clé d'API Mistral AI refusée) : fiche rédigée sans IA."


# --------------------------------------------------------------------------- configuration


ENV_COMPLET = {
    "ANTHROPIC_API_KEY": "sk-ant",
    "MISTRAL_API_KEY": "cle-secrete-mistral",
    "MISTRAL_MODEL": "mistral-large-latest",
    "MISTRAL_PRIX_ENTREE": "2",
    "MISTRAL_PRIX_SORTIE": "6,5",
    "OPENAI_API_KEY": "sk-oa",
    "OPENAI_MODEL": "modele-openai",
    "GEMINI_API_KEY": "gem",
    "GEMINI_MODEL": "modele-gemini",
    "LLM_COMPATIBLE_BASE_URL": "http://ollama:11434/v1",
    "LLM_COMPATIBLE_MODEL": "qwen3",
    "LLM_COMPATIBLE_NOM": "Ollama",
}


def test_lecture_de_la_configuration():
    config = Config.depuis_environnement({**ENV_COMPLET, "LLM_MODE": "mistral"})
    assert config.fournisseurs_utilisables == [
        ModeLLM.ANTHROPIC,
        ModeLLM.MISTRAL,
        ModeLLM.OPENAI,
        ModeLLM.GEMINI,
        ModeLLM.COMPATIBLE,
    ]
    assert config.mode_llm_effectif is ModeLLM.MISTRAL
    mistral_ = config.fournisseurs[ModeLLM.MISTRAL]
    assert mistral_.url == "https://api.mistral.ai/v1" and mistral_.tarif == Tarif(2.0, 6.5)
    assert "cle-secrete" not in repr(mistral_)  # la clé n'apparaît jamais dans les journaux
    compatible = config.fournisseurs[ModeLLM.COMPATIBLE]
    assert compatible.libelle == "Ollama" and compatible.cle_api is None and compatible.utilisable
    assert config.fournisseurs[ModeLLM.ANTHROPIC].modele == "claude-sonnet-5-5"  # seul modèle par défaut
    assert config.avertissements == []


def test_configuration_incomplete_signalee():
    config = Config.depuis_environnement({"MISTRAL_API_KEY": "mis", "LLM_MODE": "gemini"})
    assert config.fournisseurs_utilisables == []
    assert config.mode_llm_effectif is ModeLLM.GEMINI
    assert config.avertissements == [
        "Mistral AI n'est pas activé : MISTRAL_MODEL à renseigner.",
        "LLM_MODE=gemini mais Gemini (Google) n'est pas configuré : fiches rédigées sans IA.",
    ]
    assert Config.depuis_environnement({}).mode_llm_effectif is ModeLLM.SIMULE
    assert Config.depuis_environnement({"LLM_COMPATIBLE_MODEL": "m"}).avertissements == [
        "Service compatible OpenAI n'est pas activé : LLM_COMPATIBLE_BASE_URL à renseigner."
    ]
    with pytest.raises(ErreurConfiguration):
        Config.depuis_environnement({"LLM_MODE": "inconnu"})


def test_mode_auto_par_ordre_de_preference():
    seul_mistral = Config.depuis_environnement({"MISTRAL_API_KEY": "k", "MISTRAL_MODEL": "m"})
    assert seul_mistral.mode_llm_effectif is ModeLLM.MISTRAL
    assert Config.depuis_environnement(ENV_COMPLET).mode_llm_effectif is ModeLLM.ANTHROPIC


def test_fabrique_des_fournisseurs():
    config = Config.depuis_environnement(ENV_COMPLET)
    fournisseurs = fournisseurs_par_defaut(config)
    assert set(fournisseurs) == {ModeLLM.SIMULE, *config.fournisseurs_utilisables}
    assert isinstance(fournisseurs[ModeLLM.ANTHROPIC], FournisseurClaude)
    assert all(
        isinstance(fournisseurs[m], FournisseurChatCompletions)
        for m, p in PROFILS.items()
        if p.protocole is Protocole.CHAT_COMPLETIONS
    )
    assert fournisseurs[ModeLLM.COMPATIBLE].nom == "compatible" and fournisseurs[ModeLLM.COMPATIBLE].modele == "qwen3"
    with pytest.raises(ValueError, match="MISTRAL_MODEL"):
        creer_fournisseur(ConfigFournisseur.pour(ModeLLM.MISTRAL, cle_api="k"))
    tarifs = tarifs_des_redacteurs(config)
    assert tarifs[ModeLLM.MISTRAL] == Tarif(2.0, 6.5) and tarifs[ModeLLM.SIMULE] == TARIFS_PUBLICS["claude-sonnet-5-5"]
    assert ModeLLM.OPENAI not in tarifs  # prix non configurés : coût inconnu plutôt qu'inventé


def test_session_liste_les_fournisseurs_configures(mock_source, horloge, depot_utilisateurs):
    config = Config.depuis_environnement(ENV_COMPLET)
    application = creer_application(
        Config(
            fournisseurs=config.fournisseurs,
            securite=ConfigSecurite(secret_session=SECRET_TEST),
            mode_llm=ModeLLM.REPLI,
        ),
        source=mock_source,
        depot_journal=DepotMemoire(),
        horloge=horloge,
        depot_utilisateurs=depot_utilisateurs,
        depot_evaluations=DepotEvaluationsMemoire(),
    )
    modes = client_connecte(application, "resp").get("/session").json()["modes_disponibles"]
    libelles = {m["mode"]: (m["libelle"], m["modele"]) for m in modes}
    assert libelles["mistral"] == ("Mistral AI", "mistral-large-latest")
    assert libelles["compatible"] == ("Ollama", "qwen3")
    assert set(libelles) == {"simule", "anthropic", "mistral", "openai", "gemini", "compatible", "repli"}


def test_fournisseur_reel_hors_ligne_fiche_ia(mock_source, horloge):
    """Une fiche rédigée par n'importe quel fournisseur réel est une fiche « IA », avec son modèle."""
    reponses = [httpx2.Response(200, json=completion({"tool_calls": [appel("c", "soumettre_fiche", REDACTION)]}))]
    app = creer_application(
        Config(mode_llm=ModeLLM.MISTRAL, securite=ConfigSecurite(secret_session=SECRET_TEST)),
        source=mock_source,
        depot_journal=DepotMemoire(),
        horloge=horloge,
        depot_utilisateurs=DepotUtilisateursMemoire(),
        depot_evaluations=DepotEvaluationsMemoire(),
        fournisseurs={ModeLLM.MISTRAL: mistral(client_openai(reponses, []))},
    )
    fiche = app.fiches.generer("C001")
    assert fiche.mode is ModeFiche.IA and fiche.modele == "mistral-test"


# --------------------------------------------------------------------------- de bout en bout, sur le réseau

CLE_SIMULATEUR = "cle-du-simulateur"


@pytest.fixture(scope="module")
def url_simulateur_openai() -> Iterator[str]:
    """Service compatible OpenAI (rejeu des cassettes), joignable en HTTP réel."""
    yield from servir(creer_simulateur_openai(cle=CLE_SIMULATEUR))


def application_compatible(url: str, mock_source, horloge, cle: str = CLE_SIMULATEUR) -> Application:
    """Configuration identique à celle d'un serveur Ollama ou vLLM : seules l'adresse et la clé changent."""
    config = Config.depuis_environnement(
        {
            "LLM_MODE": "compatible",
            "LLM_COMPATIBLE_BASE_URL": f"{url}/v1",
            "LLM_COMPATIBLE_MODEL": "cassettes",
            "LLM_COMPATIBLE_NOM": "Simulateur OpenAI",
            "LLM_COMPATIBLE_API_KEY": cle,
            "SESSION_SECRET": SECRET_TEST,
        }
    )
    return creer_application(
        config,
        source=mock_source,
        depot_journal=DepotMemoire(),
        horloge=horloge,
        depot_utilisateurs=DepotUtilisateursMemoire(),
        depot_evaluations=DepotEvaluationsMemoire(),
    )


def test_chaine_complete_sur_le_reseau(url_simulateur_openai, mock_source, horloge):
    """SDK openai → HTTP → service compatible : même fiche que l'IA simulée, rédigée à travers le réseau."""
    app = application_compatible(url_simulateur_openai, mock_source, horloge)
    fiche = app.fiches.generer("C005")
    simulee = app.fiches.generer("C005", ModeLLM.SIMULE)
    assert fiche.mode is ModeFiche.IA and fiche.modele == "cassettes" and fiche.avertissement is None
    assert fiche.trace is not None and simulee.trace is not None
    assert fiche.trace.fournisseur == "compatible" and len(fiche.trace.etapes) == len(simulee.trace.etapes)
    assert (fiche.accroches, fiche.stock_a_ecouler, fiche.garde_fous) == (
        simulee.accroches,
        simulee.stock_a_ecouler,
        simulee.garde_fous,
    )


def test_banc_d_evaluation_a_travers_le_reseau(url_simulateur_openai, mock_source, horloge):
    app = application_compatible(url_simulateur_openai, mock_source, horloge)
    clients = ["C001", "C005", "C012"]
    campagne = app.evaluation.executer([ModeLLM.COMPATIBLE, ModeLLM.SIMULE], clients, enregistrer=False)
    compatible, simulee = campagne.syntheses
    assert compatible.redacteur is ModeLLM.COMPATIBLE and compatible.modele == "cassettes"
    assert compatible.taux_repli_pct == 0 and compatible.score_global == simulee.score_global


def test_cle_refusee_par_le_service(url_simulateur_openai, mock_source, horloge):
    app = application_compatible(url_simulateur_openai, mock_source, horloge, cle="mauvaise")
    fiche = app.fiches.generer("C005")
    assert fiche.mode is ModeFiche.REPLI
    assert fiche.avertissement == "IA indisponible (clé d'API Simulateur OpenAI refusée) : fiche rédigée sans IA."
