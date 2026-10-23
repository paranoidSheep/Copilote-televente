"""Services : choix du rédacteur, repli automatique, cache des fiches, journal."""

from __future__ import annotations

from datetime import date

import pytest

from copilote.agent.llm import ErreurFournisseurLLM
from copilote.application import creer_application, fournisseurs_par_defaut
from copilote.config import Config, ModeLLM
from copilote.domaine import ClientIntrouvable
from copilote.fiche import ModeFiche
from copilote.journal import DepotMemoire, Issue, LigneCompteRendu, NouveauCompteRendu, Origine, Reponse
from copilote.services import ErreurValidation


class FournisseurEnPanne:
    nom = "panne"
    modele = "aucun"

    def ouvrir_session(self, systeme, outils, metadonnees):
        raise ErreurFournisseurLLM("service IA injoignable")


def test_ia_simulee_par_defaut_sans_cle(application):
    fiche = application.fiches.generer("C010")
    assert fiche.mode is ModeFiche.IA_SIMULEE
    assert fiche.avertissement is None and fiche.trace is not None
    assert fiche.modele == "claude-sonnet-5-5 (simulé)"


def test_modes_disponibles():
    assert set(fournisseurs_par_defaut(Config())) == {ModeLLM.SIMULE}
    assert set(fournisseurs_par_defaut(Config(cle_anthropic_presente=True))) == {ModeLLM.SIMULE, ModeLLM.ANTHROPIC}


def test_mode_repli_explicite(application):
    fiche = application.fiches.generer("C010", ModeLLM.REPLI)
    assert fiche.mode is ModeFiche.REPLI and fiche.avertissement is None and fiche.trace is None


def test_ia_non_configuree(application):
    fiche = application.fiches.generer("C010", ModeLLM.ANTHROPIC)
    assert fiche.mode is ModeFiche.REPLI
    assert "non configurée" in (fiche.avertissement or "")


def test_bascule_en_repli_si_l_ia_echoue(mock_source, horloge):
    app = creer_application(
        Config(mode_llm=ModeLLM.ANTHROPIC),
        source=mock_source,
        depot_journal=DepotMemoire(),
        horloge=horloge,
        fournisseurs={ModeLLM.ANTHROPIC: FournisseurEnPanne()},
    )
    fiche = app.fiches.generer("C001")
    assert fiche.mode is ModeFiche.REPLI
    assert fiche.avertissement == "IA indisponible (service IA injoignable) : fiche rédigée sans IA."
    assert fiche.trace is not None  # la trace de l'échec est conservée pour le diagnostic
    assert 2 <= len(fiche.accroches) <= 3


def test_cache_et_regeneration(application):
    premiere = application.fiches.generer("C010")
    assert application.fiches.generer("C010") is premiere
    assert application.fiches.generer("C010", regenerer=True) is not premiere
    assert application.fiches.generer("C010", ModeLLM.REPLI) is not premiere  # cache distinct par mode


def test_client_inconnu(application):
    with pytest.raises(ClientIntrouvable):
        application.fiches.generer("C999")


def ligne(code: str, reponse: Reponse, origine: Origine = Origine.STOCK) -> LigneCompteRendu:
    return LigneCompteRendu(
        code=code,
        libelle=code,
        unite="kg",
        origine=origine,
        reponse=reponse,
        quantite=4 if reponse is Reponse.ACCEPTE else 0,
        prix_unitaire_ht=9.9,
        remise_pct=20,
    )


def test_compte_rendu_invalide_la_fiche_et_alimente_les_garde_fous(application, horloge):
    avant = application.fiches.generer("C010")
    assert any(s.code == "FR007" for s in avant.stock_a_ecouler)

    enregistre = application.journal.enregistrer(
        NouveauCompteRendu(
            client_id="C010",
            televendeur="Julie Moreau",
            issue=Issue.COMMANDE,
            lignes=[ligne("FR008", Reponse.ACCEPTE), ligne("FR007", Reponse.REFUSE)],
        )
    )
    assert enregistre.cree_le == horloge.instant

    apres = application.fiches.generer("C010")
    assert apres is not avant  # le cache du client a été invalidé
    assert all(s.code != "FR007" for s in apres.stock_a_ecouler)  # offre refusée : non reproposée
    assert any("FR007" in g.message for g in apres.garde_fous)
    assert apres.appels_precedents.appels[0].produits_refuses == ["FR007"]


def test_compte_rendu_produit_inconnu(application):
    with pytest.raises(ErreurValidation):
        application.journal.enregistrer(
            NouveauCompteRendu(
                client_id="C010", televendeur="Julie", issue=Issue.COMMANDE, lignes=[ligne("XX999", Reponse.ACCEPTE)]
            )
        )
    with pytest.raises(ClientIntrouvable):
        application.journal.enregistrer(NouveauCompteRendu(client_id="C999", televendeur="J", issue=Issue.INJOIGNABLE))


def test_texte_de_saisie_erp(application):
    cr = application.journal.enregistrer(
        NouveauCompteRendu(
            client_id="C010",
            televendeur="Julie Moreau",
            issue=Issue.COMMANDE,
            notes="Livrer tôt",
            lignes=[ligne("FR007", Reponse.ACCEPTE), ligne("FR008", Reponse.REFUSE)],
        )
    )
    texte = application.journal.texte_saisie_erp(cr)
    assert "Pizza Momo (C010)" in texte
    assert "FR007" in texte and "FR008" not in texte
    assert "7,92 € (9,90 € -20 %)" in texte
    assert "Total HT estimé : 31,68 €" in texte and "Livrer tôt" in texte


def test_appel_du_jour_compte_comme_passe(application):
    application.journal.enregistrer(
        NouveauCompteRendu(client_id="C020", televendeur="Julie", issue=Issue.RAPPELER, rappel_le=date(2026, 10, 23))
    )
    file = application.pilotage.file_appels()
    c020 = next(a for a in file.appels if a.client.id == "C020")
    # l'appel du jour (« rappeler ») compte comme déjà passé : le client passe en fin de liste
    assert c020.deja_appele_aujourdhui


def test_statistiques_sur_la_periode(application):
    application.journal.enregistrer(
        NouveauCompteRendu(
            client_id="C010", televendeur="Julie", issue=Issue.COMMANDE, lignes=[ligne("FR007", Reponse.ACCEPTE)]
        )
    )
    stats = application.journal.statistiques(7)
    assert stats.nb_appels == 1 and stats.ca_accepte_ht == 31.68
