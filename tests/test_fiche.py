"""Fiche d'appel : garde-fous de l'assemblage, mode repli, panier et rendu texte."""

from __future__ import annotations

from datetime import date, datetime

from copilote.analyses import construire_contexte
from copilote.config import ModeLLM
from copilote.fiche import ModeFiche, Redaction, TypeCorrection, assembler_fiche, rediger_sans_ia
from copilote.fiche import formatage as fmt
from copilote.fiche.assemblage import noms_usuels
from copilote.journal import Issue, NouveauCompteRendu, Origine, Reponse
from tests.test_analyses import compte_rendu, refus
from tests.test_services import ligne

MAINTENANT = datetime(2026, 10, 23, 10, 30, 12, 345)


def redaction(**champs) -> Redaction:
    base = {
        "resume_habitudes": "Résumé",
        "produits_manquants": [],
        "stock_a_ecouler": [],
        "suggestions": [],
        "accroches": ["Une", "Deux"],
        "points_attention": [],
    }
    return Redaction.model_validate({**base, **champs})


def test_produits_inventes_ecartes_et_remise_plafonnee(ref_simple):
    contexte = construire_contexte(ref_simple, "R1", [])
    fiche = assembler_fiche(
        contexte,
        redaction(
            produits_manquants=[{"code": "P2", "commentaire": " à relancer "}, {"code": "INVENTE", "commentaire": "x"}],
            stock_a_ecouler=[
                {"code": "P1", "remise_pct": 80, "argument": "promo"},
                {"code": "P5", "remise_pct": 5, "argument": "x"},
            ],
            suggestions=[{"code": "P4", "argument": "les autres l'adorent"}, {"code": "P1", "argument": "déjà acheté"}],
        ),
        mode=ModeFiche.IA,
        genere_le=MAINTENANT,
        modele="test",
    )
    assert [m.code for m in fiche.produits_manquants] == ["P2"]
    assert fiche.produits_manquants[0].commentaire == "à relancer"
    assert [s.code for s in fiche.stock_a_ecouler] == ["P1"]
    assert fiche.stock_a_ecouler[0].remise_pct == 30 and fiche.stock_a_ecouler[0].prix_propose_ht == 7.0
    assert fiche.stock_a_ecouler[0].quantite_conseillee == 5  # quantité habituelle du client
    assert [s.code for s in fiche.suggestions] == ["P4"]
    assert fiche.genere_le.microsecond == 0
    assert any("INVENTE" in g.message for g in fiche.garde_fous)
    assert any("ramenée de 80 % à 30 %" in g.message for g in fiche.garde_fous)
    assert {g.type for g in fiche.garde_fous} >= {TypeCorrection.PRODUIT_INCONNU, TypeCorrection.REMISE_PLAFONNEE}
    assert next(g for g in fiche.garde_fous if g.type is TypeCorrection.PRODUIT_INCONNU).codes == ["INVENTE"]


def test_offres_refusees_retirees_et_stock_complete(ref_simple):
    crs = [compte_rendu("R1", 2, lignes=[refus("P4", Origine.SUGGESTION), refus("P2", Origine.STOCK)])]
    contexte = construire_contexte(ref_simple, "R1", crs)
    fiche = assembler_fiche(
        contexte,
        redaction(
            produits_manquants=[{"code": "P2", "commentaire": "habituel"}],
            suggestions=[{"code": "P4", "argument": "x"}],
            stock_a_ecouler=[{"code": "P9", "remise_pct": 10, "argument": "inconnu"}],
        ),
        mode=ModeFiche.IA,
        genere_le=MAINTENANT,
    )
    assert [m.code for m in fiche.produits_manquants] == ["P2"]  # un habituel n'est jamais masqué
    assert fiche.suggestions == []
    assert [s.code for s in fiche.stock_a_ecouler] == ["P1"]  # complété depuis les analyses
    assert any("refusé récemment" in g.message for g in fiche.garde_fous)
    assert any("ajouté(s) depuis les analyses" in g.message for g in fiche.garde_fous)
    complement = next(g for g in fiche.garde_fous if g.type is TypeCorrection.STOCK_COMPLETE)
    assert complement.codes and set(complement.codes) <= {s.code for s in fiche.stock_a_ecouler}


def test_selection_vide_voulue_respectee(ref_simple):
    fiche = assembler_fiche(
        construire_contexte(ref_simple, "R1", []), redaction(), mode=ModeFiche.IA, genere_le=MAINTENANT
    )
    assert fiche.stock_a_ecouler == [] and fiche.garde_fous == []


def test_accroches_completees_et_limitees(ref_simple):
    contexte = construire_contexte(ref_simple, "R1", [])
    fiche = assembler_fiche(contexte, redaction(accroches=["  "]), mode=ModeFiche.IA, genere_le=MAINTENANT)
    assert len(fiche.accroches) == 2
    fiche = assembler_fiche(
        contexte, redaction(accroches=["a", "b", "c", "d"]), mode=ModeFiche.IA, genere_le=MAINTENANT
    )
    assert fiche.accroches == ["a", "b", "c"]


def test_mode_repli_sur_tout_le_mock(ref_mock):
    for client_id in ref_mock.clients:
        contexte = construire_contexte(ref_mock, client_id, [])
        fiche = assembler_fiche(contexte, rediger_sans_ia(contexte), mode=ModeFiche.REPLI, genere_le=MAINTENANT)
        assert fiche.garde_fous == [], client_id  # le repli respecte toujours les règles
        assert 2 <= len(fiche.accroches) <= 3
        assert fiche.client.contact.split()[-1] in " ".join(fiche.accroches) or len(fiche.accroches) == 2
        assert "FICHE D'APPEL" in fiche.texte


def test_panier_sans_doublon_et_total(ref_mock):
    contexte = construire_contexte(ref_mock, "C005", [])
    fiche = assembler_fiche(contexte, rediger_sans_ia(contexte), mode=ModeFiche.REPLI, genere_le=MAINTENANT)
    codes = [l.code for l in fiche.panier.lignes]
    assert len(codes) == len(set(codes))
    assert fiche.panier.total_ht == round(sum(l.montant_ht for l in fiche.panier.lignes), 2)
    lieu = next(l for l in fiche.panier.lignes if l.code == "FR033")  # manquant ET à écouler
    assert lieu.origine is Origine.STOCK and lieu.remise_pct > 0


def test_rendu_texte(ref_simple):
    contexte = construire_contexte(ref_simple, "R1", [])
    fiche = assembler_fiche(contexte, rediger_sans_ia(contexte), mode=ModeFiche.REPLI, genere_le=MAINTENANT)
    assert "PANIER PROPOSÉ" in fiche.texte and "[décroché]" in fiche.texte
    assert "mode repli" in fiche.texte


def test_formatage():
    assert fmt.euros(1234.5) == "1 234,50 €"
    assert fmt.quantite(2, "carton") == "2 cartons"
    assert fmt.quantite(3, "plateau") == "3 plateaux"
    assert fmt.quantite(6, "kg") == "6 kg"
    assert fmt.quantite(1, "seau") == "1 seau"
    assert fmt.liste(["a", "b", "c"]) == "a, b et c"
    assert fmt.jours(1) == "jours" and fmt.jours(3.5) == "3,5 jours"
    assert fmt.minuscule_initiale("Sorbet citron 2,5 L") == "sorbet citron 2,5 L"


def test_rappel_promis_toujours_mentionne(ref_simple):
    crs = [compte_rendu("R1", 1, Issue.RAPPELER, rappel=date(2026, 10, 23))]
    contexte = construire_contexte(ref_simple, "R1", crs)
    fiche = assembler_fiche(contexte, redaction(), mode=ModeFiche.IA, genere_le=MAINTENANT)
    assert fiche.points_attention[0] == "Le client a demandé à être rappelé le 23/10/2026."
    deja = redaction(points_attention=["Rappel promis pour ce matin."])
    fiche = assembler_fiche(contexte, deja, mode=ModeFiche.IA, genere_le=MAINTENANT)
    assert fiche.points_attention == ["Rappel promis pour ce matin."]


def test_noms_usuels_d_un_produit():
    assert noms_usuels("Cordon bleu de volaille, carton de 40") == ["cordon bleu de volaille", "cordon bleu", "cordon"]
    assert noms_usuels("Ratatouille cuisinée 2,5 kg") == ["ratatouille cuisinée", "ratatouille"]
    assert noms_usuels("Pain 400 g") == []  # trop générique pour conclure


def test_accroche_vantant_une_offre_refusee_retiree(application):
    """Cas réel : l'IA simulée vante la ratatouille (SG014) que le client vient de refuser."""
    avant = application.fiches.produire("C019", ModeLLM.SIMULE).fiche
    assert any("ratatouille" in a for a in avant.accroches)
    application.journal.enregistrer(
        NouveauCompteRendu(
            client_id="C019",
            televendeur="Julie Moreau",
            issue=Issue.PAS_DE_BESOIN,
            lignes=[ligne("SG014", Reponse.REFUSE)],
        )
    )
    apres = application.fiches.produire("C019", ModeLLM.SIMULE).fiche
    assert not any("ratatouille" in a for a in apres.accroches) and len(apres.accroches) >= 2
    retrait = next(g for g in apres.garde_fous if g.type is TypeCorrection.ACCROCHE_RETIREE)
    assert retrait.codes == ["SG014"]


def test_nom_partage_avec_un_produit_conserve_ne_suffit_pas(ref_simple):
    """« produit » désigne aussi les produits conservés : l'accroche n'est pas retirée à tort."""
    crs = [compte_rendu("R1", 2, lignes=[refus("P4", Origine.SUGGESTION)])]
    fiche = assembler_fiche(
        construire_contexte(ref_simple, "R1", crs),
        redaction(
            stock_a_ecouler=[{"code": "P1", "remise_pct": 30, "argument": "x"}],  # « Produit P1 » est conservé
            suggestions=[{"code": "P4", "argument": "x"}],
            accroches=["Le produit P4 ?", "Autre chose ?"],
        ),
        mode=ModeFiche.IA,
        genere_le=MAINTENANT,
    )
    assert fiche.accroches == ["Le produit P4 ?", "Autre chose ?"]
