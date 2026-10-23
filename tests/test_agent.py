"""Tests de l'agent : mode repli, boucle de tool use (Claude simulé) et garde-fous."""

from __future__ import annotations

from types import SimpleNamespace

import anthropic
import httpx
import pytest

from agent.agent import generer_fiche
from agent.fiche import Redaction, assembler_fiche, redaction_repli
from agent.tools import contexte_complet
from datahub.base import ClientIntrouvable

# ------------------------------------------------------------------ mode repli


@pytest.fixture
def sans_cle(monkeypatch):
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)


def test_mode_repli_sans_cle(sans_cle, mock_source):
    fiche = generer_fiche(mock_source, "C010")
    assert fiche.mode == "repli"
    assert "ANTHROPIC_API_KEY" in fiche.avertissement
    assert fiche.client.id == "C010"
    assert fiche.habitudes.resume and fiche.habitudes.panier_moyen_ht > 0
    assert 2 <= len(fiche.accroches) <= 3
    assert "FICHE D'APPEL" in fiche.texte and "ACCROCHES" in fiche.texte


def test_mode_repli_pour_tous_les_clients(sans_cle, mock_source):
    for c in mock_source.get_clients():
        fiche = generer_fiche(mock_source, c.id)
        assert 2 <= len(fiche.accroches) <= 3, c.id
        for s in fiche.stock_a_ecouler:
            assert 0 <= s.remise_pct <= 30


def test_client_inconnu(sans_cle, mock_source):
    with pytest.raises(ClientIntrouvable):
        generer_fiche(mock_source, "C999")


# ------------------------------------------------------------ garde-fous


def test_assemblage_ignore_les_produits_inventes_et_plafonne_les_remises(source_simple):
    contexte = contexte_complet(source_simple, "R1")
    redaction = Redaction(
        resume_habitudes="Résumé",
        produits_manquants=[{"code": "P2", "commentaire": "à relancer"}, {"code": "INVENTE", "commentaire": "x"}],
        stock_a_ecouler=[{"code": "P1", "remise_pct": 80, "argument": "promo"}, {"code": "P5", "remise_pct": 10, "argument": "x"}],
        suggestions=[{"code": "P4", "argument": "les autres restaurants l'adorent"}, {"code": "P1", "argument": "déjà acheté"}],
        accroches=["Une seule accroche"],
        points_attention=[],
    )
    fiche = assembler_fiche(contexte, redaction, mode="ia", modele="test")
    assert [m.code for m in fiche.produits_manquants] == ["P2"]
    assert [s.code for s in fiche.stock_a_ecouler] == ["P1"]  # P5 n'était pas proposé par l'outil
    assert fiche.stock_a_ecouler[0].remise_pct == 30  # 80 % demandé, plafonné à la remise suggérée
    assert fiche.stock_a_ecouler[0].prix_remise_ht == 7.0
    assert [s.code for s in fiche.suggestions] == ["P4"]
    assert len(fiche.accroches) == 2  # complétée automatiquement


def test_redaction_repli_reprend_les_donnees_des_outils(source_simple):
    contexte = contexte_complet(source_simple, "R1")
    redaction = redaction_repli(contexte)
    assert [m.code for m in redaction.produits_manquants] == ["P2"]
    assert "concurrent" in redaction.produits_manquants[0].commentaire
    assert redaction.stock_a_ecouler[0].remise_pct == 30


# ---------------------------------------------------- boucle de tool use (Claude simulé)


def bloc_outil(id_, nom, entree):
    return SimpleNamespace(type="tool_use", id=id_, name=nom, input=entree)


def reponse(stop_reason, *blocs):
    return SimpleNamespace(stop_reason=stop_reason, content=list(blocs))


class FauxClaude:
    """Imite `anthropic.Anthropic` : rejoue des réponses scénarisées et mémorise les requêtes."""

    def __init__(self, reponses):
        self.reponses = list(reponses)
        self.requetes = []
        self.beta = SimpleNamespace(messages=SimpleNamespace(create=self._create))

    def _create(self, **kwargs):
        # copie des messages : la liste est modifiée par la boucle après l'appel
        self.requetes.append({**kwargs, "messages": list(kwargs["messages"])})
        reponse_suivante = self.reponses.pop(0)
        if isinstance(reponse_suivante, Exception):
            raise reponse_suivante
        return reponse_suivante


REDACTION_IA = {
    "resume_habitudes": "Restaurant fidèle qui commande chaque vendredi.",
    "produits_manquants": [{"code": "P2", "commentaire": "Plus commandé depuis 5 semaines."}],
    "stock_a_ecouler": [{"code": "P1", "remise_pct": 20, "argument": "Produit phare, DLC demain."}],
    "suggestions": [{"code": "P4", "argument": "Adopté par les autres restaurants."}],
    "accroches": ["Bonjour M. Test, on refait le plein de P2 ?", "J'ai du P1 à -20 % !"],
    "points_attention": ["P2 décroché"],
}


def test_boucle_tool_use(source_simple):
    faux = FauxClaude([
        # 1er tour : Claude appelle deux outils en parallèle
        reponse("tool_use", bloc_outil("t1", "historique_client", {"client_id": "R1"}),
                bloc_outil("t2", "stock_a_ecouler", {"client_id": "R1"})),
        # 2e tour : il soumet sa rédaction
        reponse("tool_use", bloc_outil("t3", "soumettre_fiche", REDACTION_IA)),
    ])
    fiche = generer_fiche(source_simple, "R1", client_anthropic=faux)

    assert fiche.mode == "ia" and fiche.avertissement is None
    assert fiche.stock_a_ecouler[0].remise_pct == 20
    assert fiche.accroches == REDACTION_IA["accroches"]

    # Les deux résultats d'outils repartent dans UN seul message utilisateur
    second_appel = faux.requetes[1]["messages"]
    resultats = second_appel[-1]["content"]
    assert [r["tool_use_id"] for r in resultats] == ["t1", "t2"]
    assert '"nb_commandes": 10' in resultats[0]["content"]
    # Paramètres d'appel
    assert faux.requetes[0]["model"] == "claude-sonnet-5-5"
    assert {o["name"] for o in faux.requetes[0]["tools"]} >= {"soumettre_fiche", "suggestions_croisees"}


def test_boucle_relance_si_pas_de_soumission(source_simple):
    texte = SimpleNamespace(type="text", text="Voici la fiche…")
    faux = FauxClaude([
        reponse("end_turn", texte),
        reponse("tool_use", bloc_outil("t1", "soumettre_fiche", REDACTION_IA)),
    ])
    fiche = generer_fiche(source_simple, "R1", client_anthropic=faux)
    assert fiche.mode == "ia"
    assert "soumettre_fiche" in faux.requetes[1]["messages"][-1]["content"]


def test_erreur_d_outil_renvoyee_a_claude(source_simple):
    faux = FauxClaude([
        reponse("tool_use", bloc_outil("t1", "historique_client", {"client_id": "INCONNU"})),
        reponse("tool_use", bloc_outil("t2", "soumettre_fiche", REDACTION_IA)),
    ])
    generer_fiche(source_simple, "R1", client_anthropic=faux)
    resultat = faux.requetes[1]["messages"][-1]["content"][0]
    assert resultat["is_error"] is True


@pytest.mark.parametrize(
    "probleme",
    [
        anthropic.APIConnectionError(request=httpx.Request("POST", "https://api.anthropic.com")),
        reponse("refusal"),
        reponse("tool_use", bloc_outil("t1", "soumettre_fiche", {"accroches": "pas une liste"})),
    ],
    ids=["reseau", "refus", "redaction-invalide"],
)
def test_bascule_en_mode_repli_si_l_ia_echoue(source_simple, probleme):
    fiche = generer_fiche(source_simple, "R1", client_anthropic=FauxClaude([probleme]))
    assert fiche.mode == "repli"
    assert fiche.avertissement.startswith("IA indisponible")
    assert len(fiche.accroches) >= 2
