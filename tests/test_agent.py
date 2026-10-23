"""Agent : outils, boucle de rédaction, IA simulée et adaptateur Claude (HTTP simulé)."""

from __future__ import annotations

import json
from collections.abc import Mapping, Sequence
from datetime import date

import anthropic
import httpx2  # transport du SDK anthropic 2.x
import pytest

from copilote.agent import BoiteAOutils, ErreurRedaction, RedacteurIA, creer_boite_outils, definition_soumission
from copilote.agent.llm import (
    AppelOutil,
    Arret,
    DefinitionOutil,
    ErreurFournisseurLLM,
    FournisseurClaude,
    FournisseurSimule,
    MessageUtilisateur,
    ParametresClaude,
    ReponseLLM,
    ResultatOutil,
    Usage,
)
from copilote.agent.llm.claude import BETA_BASCULE_REFUS
from copilote.agent.outils import schema_autonome
from copilote.analyses import construire_contexte
from copilote.domaine import ClientIntrouvable
from copilote.fiche import Redaction, TypeEtape
from scripts.cassettes import verifier_toutes

REDACTION = {
    "resume_habitudes": "Restaurant fidèle qui commande chaque vendredi.",
    "produits_manquants": [{"code": "P2", "commentaire": "Plus commandé depuis 5 semaines."}],
    "stock_a_ecouler": [{"code": "P1", "remise_pct": 20, "argument": "DLC demain."}],
    "suggestions": [{"code": "P4", "argument": "Adopté par les autres restaurants."}],
    "accroches": ["Bonjour M. Test, on refait le plein de P2 ?", "J'ai du P1 à -20 % !"],
    "points_attention": [],
}

# ------------------------------------------------------------------- outils


def test_schemas_d_outils_autonomes_et_stricts(ref_simple):
    definitions = [*creer_boite_outils(ref_simple, "R1", []).definitions(), definition_soumission()]
    assert [d.nom for d in definitions] == [
        "historique_client",
        "produits_habituels_manquants",
        "stock_a_ecouler",
        "suggestions_croisees",
        "historique_appels",
        "details_produit",
        "soumettre_fiche",
    ]
    for d in definitions:
        texte = json.dumps(d.schema_entree)
        assert "$ref" not in texte and "$defs" not in texte
        assert d.schema_entree["additionalProperties"] is False
    soumission = definitions[-1].schema_entree
    assert set(soumission["required"]) == set(Redaction.model_fields)  # tout est obligatoire


def test_schema_autonome_resout_les_references():
    schema = schema_autonome(Redaction)
    articles = schema["properties"]["stock_a_ecouler"]["items"]
    assert articles["properties"]["remise_pct"]["type"] == "integer"


def test_outils_verrouilles_sur_le_client(ref_simple):
    boite = creer_boite_outils(ref_simple, "R1", [])
    ok = boite.executer(AppelOutil(id="1", nom="historique_client", arguments={"client_id": "R1"}))
    assert not ok.est_erreur and json.loads(ok.contenu)["nb_commandes"] == 10
    autre = boite.executer(AppelOutil(id="2", nom="historique_client", arguments={"client_id": "R2"}))
    assert autre.est_erreur and "Accès limité" in autre.contenu
    invalide = boite.executer(AppelOutil(id="3", nom="details_produit", arguments={"client_id": "R1"}))
    assert invalide.est_erreur and "Arguments invalides" in invalide.contenu
    inconnu = boite.executer(AppelOutil(id="4", nom="supprimer_commande", arguments={}))
    assert inconnu.est_erreur
    produit = boite.executer(AppelOutil(id="5", nom="details_produit", arguments={"client_id": "R1", "code": "XX"}))
    assert produit.est_erreur and "Produit inconnu" in produit.contenu
    with pytest.raises(ClientIntrouvable):
        creer_boite_outils(ref_simple, "INCONNU", [])


# ------------------------------------------------------------------- boucle de rédaction


class SessionScenarisee:
    def __init__(self, reponses: list[ReponseLLM | Exception]):
        self.reponses = reponses
        self.messages: list[MessageUtilisateur] = []

    def envoyer(self, message: MessageUtilisateur) -> ReponseLLM:
        self.messages.append(message)
        suivante = self.reponses.pop(0)
        if isinstance(suivante, Exception):
            raise suivante
        return suivante


class FournisseurScenarise:
    nom = "test"
    modele = "modele-test"

    def __init__(self, reponses: list[ReponseLLM | Exception]):
        self.session = SessionScenarisee(reponses)
        self.outils: list[DefinitionOutil] = []

    def ouvrir_session(self, systeme: str, outils: Sequence[DefinitionOutil], metadonnees: Mapping[str, str]):
        self.outils = list(outils)
        assert metadonnees["client_id"] == "R1"
        return self.session


def reponse(arret: Arret, *appels: tuple[str, dict], textes=()) -> ReponseLLM:
    return ReponseLLM(
        arret=arret,
        modele="modele-test",
        textes=list(textes),
        appels=[AppelOutil(id=f"t{i}", nom=n, arguments=a) for i, (n, a) in enumerate(appels)],
        usage=Usage(jetons_entree=100, jetons_sortie=20),
    )


def rediger(ref, fournisseur):
    return RedacteurIA(fournisseur).rediger(ref.client("R1"), date(2026, 10, 23), creer_boite_outils(ref, "R1", []))


def test_boucle_complete(ref_simple):
    fournisseur = FournisseurScenarise(
        [
            reponse(Arret.OUTILS, ("historique_client", {"client_id": "R1"}), ("stock_a_ecouler", {"client_id": "R1"})),
            reponse(Arret.OUTILS, ("soumettre_fiche", REDACTION)),
        ]
    )
    resultat = rediger(ref_simple, fournisseur)
    assert resultat.redaction.accroches == REDACTION["accroches"]
    # Les deux résultats d'outils repartent ensemble, dans un seul message
    resultats = fournisseur.session.messages[1]
    assert isinstance(resultats, list) and [r.appel_id for r in resultats] == ["t0", "t1"]
    types = [e.type for e in resultat.trace.etapes]
    assert types == [TypeEtape.APPEL_LLM, TypeEtape.OUTIL, TypeEtape.OUTIL, TypeEtape.APPEL_LLM]
    assert resultat.trace.jetons_entree == 200
    assert "soumettre_fiche" in {o.nom for o in fournisseur.outils}


def test_relance_si_pas_de_soumission(ref_simple):
    fournisseur = FournisseurScenarise(
        [
            reponse(Arret.FIN, textes=["Voici la fiche…"]),
            reponse(Arret.OUTILS, ("soumettre_fiche", REDACTION)),
        ]
    )
    rediger(ref_simple, fournisseur)
    assert "soumettre_fiche" in str(fournisseur.session.messages[1])


@pytest.mark.parametrize(
    ("reponses", "raison"),
    [
        ([reponse(Arret.REFUS)], "refusé"),
        ([reponse(Arret.LIMITE)], "tronquée"),
        ([reponse(Arret.OUTILS, ("soumettre_fiche", {"accroches": "pas une liste"}))], "mal formée"),
        ([reponse(Arret.FIN), reponse(Arret.FIN)], "pas soumis"),
        ([ErreurFournisseurLLM("service IA injoignable")], "injoignable"),
        ([reponse(Arret.OUTILS, ("historique_client", {"client_id": "R1"}))] * 6, "6 échanges"),
    ],
)
def test_echecs_de_redaction(ref_simple, reponses, raison):
    with pytest.raises(ErreurRedaction) as exc:
        rediger(ref_simple, FournisseurScenarise(list(reponses)))
    assert raison in exc.value.raison
    assert exc.value.trace.duree_totale_ms >= 0


# ------------------------------------------------------------------- IA simulée


def test_cassettes_valides_pour_tous_les_clients(ref_mock):
    assert verifier_toutes(ref_mock) == []


def test_ia_simulee_de_bout_en_bout(ref_mock):
    resultat = RedacteurIA(FournisseurSimule()).rediger(
        ref_mock.client("C005"), ref_mock.date_du_jour, creer_boite_outils(ref_mock, "C005", [])
    )
    noms = [e.nom for e in resultat.trace.etapes if e.type is TypeEtape.OUTIL]
    assert "details_produit" in noms and len(noms) == 6
    assert not any(e.erreur for e in resultat.trace.etapes)
    assert resultat.redaction.produits_manquants[0].code == "FR033"


def test_ia_simulee_exige_tous_les_resultats(ref_mock):
    session = FournisseurSimule().ouvrir_session(
        "systeme",
        [*creer_boite_outils(ref_mock, "C001", []).definitions(), definition_soumission()],
        {"client_id": "C001"},
    )
    premiere = session.envoyer("bonjour")
    assert premiere.arret is Arret.OUTILS and len(premiere.appels) == 5
    with pytest.raises(ErreurFournisseurLLM):
        session.envoyer([ResultatOutil(appel_id=premiere.appels[0].id, contenu="{}")])


def test_ia_simulee_sans_cassette(tmp_path, ref_mock):
    with pytest.raises(ErreurFournisseurLLM):
        FournisseurSimule(dossier=tmp_path).ouvrir_session("s", [definition_soumission()], {"client_id": "C001"})


def test_ia_simulee_latence(ref_mock):
    attentes: list[float] = []
    fournisseur = FournisseurSimule(latence_ms=250, dormir=attentes.append)
    RedacteurIA(fournisseur).rediger(
        ref_mock.client("C001"), ref_mock.date_du_jour, creer_boite_outils(ref_mock, "C001", [])
    )
    assert attentes and all(a == 0.25 for a in attentes)


# ------------------------------------------------------------------- adaptateur Claude (HTTP simulé)


def message_api(contenu: list[dict], stop: str = "tool_use") -> dict:
    return {
        "id": "msg_1",
        "type": "message",
        "role": "assistant",
        "model": "claude-sonnet-5-5",
        "content": contenu,
        "stop_reason": stop,
        "stop_sequence": None,
        "usage": {"input_tokens": 1200, "output_tokens": 80},
    }


def client_anthropic(reponses: list[httpx2.Response], requetes: list[httpx2.Request]) -> anthropic.Anthropic:
    def transport(requete: httpx2.Request) -> httpx2.Response:
        requetes.append(requete)
        return reponses.pop(0)

    return anthropic.Anthropic(
        api_key="test", http_client=httpx2.Client(transport=httpx2.MockTransport(transport)), max_retries=0
    )


def test_claude_boucle_complete_via_le_sdk(ref_simple):
    requetes: list[httpx2.Request] = []
    reponses = [
        httpx2.Response(
            200,
            json=message_api(
                [
                    {"type": "text", "text": "Je consulte l'historique."},
                    {"type": "tool_use", "id": "toolu_1", "name": "historique_client", "input": {"client_id": "R1"}},
                ]
            ),
        ),
        httpx2.Response(
            200,
            json=message_api(
                [
                    {"type": "tool_use", "id": "toolu_2", "name": "soumettre_fiche", "input": REDACTION},
                ]
            ),
        ),
    ]
    fournisseur = FournisseurClaude(ParametresClaude(modele="claude-sonnet-5-5"), client_anthropic(reponses, requetes))
    resultat = RedacteurIA(fournisseur).rediger(
        ref_simple.client("R1"), date(2026, 10, 23), creer_boite_outils(ref_simple, "R1", [])
    )

    assert resultat.redaction.stock_a_ecouler[0].code == "P1"
    premiere = json.loads(requetes[0].content)
    assert premiere["model"] == "claude-sonnet-5-5"
    assert premiere["output_config"] == {"effort": "medium"}
    assert premiere["fallbacks"] == "default"
    assert BETA_BASCULE_REFUS in requetes[0].headers["anthropic-beta"]
    assert all(outil["strict"] is True for outil in premiere["tools"])
    seconde = json.loads(requetes[1].content)
    assert [m["role"] for m in seconde["messages"]] == ["user", "assistant", "user"]
    retour = seconde["messages"][2]["content"][0]
    assert retour["type"] == "tool_result" and retour["tool_use_id"] == "toolu_1"
    assert resultat.trace.etapes[0].jetons_entree == 1200


def test_claude_sans_bascule(ref_simple):
    requetes: list[httpx2.Request] = []
    reponses = [
        httpx2.Response(
            200, json=message_api([{"type": "tool_use", "id": "t", "name": "soumettre_fiche", "input": REDACTION}])
        )
    ]
    fournisseur = FournisseurClaude(
        ParametresClaude(modele="m", bascule_refus=False), client_anthropic(reponses, requetes)
    )
    RedacteurIA(fournisseur).rediger(
        ref_simple.client("R1"), date(2026, 10, 23), creer_boite_outils(ref_simple, "R1", [])
    )
    assert "fallbacks" not in json.loads(requetes[0].content)


@pytest.mark.parametrize(
    ("statut", "raison"),
    [(429, "limite d'utilisation"), (401, "refusée"), (500, "erreur du service IA (500)")],
)
def test_claude_erreurs_http_traduites(ref_simple, statut, raison):
    erreur = {"type": "error", "error": {"type": "x", "message": "x"}}
    fournisseur = FournisseurClaude(
        ParametresClaude(modele="m"), client_anthropic([httpx2.Response(statut, json=erreur)], [])
    )
    with pytest.raises(ErreurRedaction) as exc:
        RedacteurIA(fournisseur).rediger(
            ref_simple.client("R1"), date(2026, 10, 23), creer_boite_outils(ref_simple, "R1", [])
        )
    assert raison in exc.value.raison


def test_claude_refus_traduit(ref_simple):
    reponses = [httpx2.Response(200, json=message_api([], stop="refusal"))]
    fournisseur = FournisseurClaude(ParametresClaude(modele="m"), client_anthropic(reponses, []))
    with pytest.raises(ErreurRedaction, match="refusé"):
        RedacteurIA(fournisseur).rediger(
            ref_simple.client("R1"), date(2026, 10, 23), creer_boite_outils(ref_simple, "R1", [])
        )


def test_contexte_et_boite_coherents(ref_mock):
    """Les outils renvoient exactement les analyses du contexte (même source de vérité)."""
    contexte = construire_contexte(ref_mock, "C010", [])
    boite: BoiteAOutils = creer_boite_outils(ref_mock, "C010", [])
    stock = json.loads(
        boite.executer(AppelOutil(id="1", nom="stock_a_ecouler", arguments={"client_id": "C010"})).contenu
    )
    assert [p["code"] for p in stock["produits"]] == [p.code for p in contexte.stock.produits]
