// Qualité IA (labo) : banc d'évaluation des fiches, comparaison des rédacteurs et historique des versions du prompt.
import { api } from "../api.js";
import { badge, barresHorizontales, bouton, carte, chargement, kpi, messageErreur, titrePage, vide } from "../composants.js";
import { h, remplacer } from "../dom.js";
import { dateCourte, heure, LIBELLES, nombre } from "../format.js";
import { ongletsLabo } from "./onglets-labo.js";
const INTERVALLE_SUIVI_MS = 800;
const varianteScore = (score) => (score >= 90 ? "succes" : score >= 75 ? "attention" : "alerte");
const dollars = (montant) => `${montant.toLocaleString("fr-FR", { maximumFractionDigits: 4 })} $`;
const duree = (ms) => (ms < 1000 ? `${ms} ms` : `${nombre(ms / 1000)} s`);
function jaugeCritere(libelle, valeur) {
    return h("div", { classe: "critere" }, h("span", null, libelle), h("span", { classe: "jauge" }, h("span", { classe: varianteScore(valeur), attrs: { style: `width:${Math.max(2, valeur)}%` } })), h("span", { classe: "nombre gras" }, nombre(valeur)));
}
function carteSynthese(s) {
    const cout = s.cout_par_fiche_usd === null ? "—" : dollars(s.cout_par_fiche_usd);
    return carte(null, [
        h("div", { classe: "entree" }, h("div", null, h("div", { classe: "gras" }, LIBELLES.modeLLM[s.redacteur]), h("div", { classe: "meta" }, s.modele ?? "gabarits, sans IA")), h("div", { classe: `score-redacteur ${varianteScore(s.score_global)}` }, nombre(s.score_global))),
        h("div", { classe: "pile", attrs: { style: "gap:6px;margin:12px 0" } }, jaugeCritere("Fidélité", s.score_fidelite), jaugeCritere("Couverture", s.score_couverture), jaugeCritere("Format", s.score_format)),
        h("div", { classe: "kpis" }, kpi(`${s.fiches_sans_defaut}/${s.nb_fiches}`, "Fiches sans défaut"), kpi(`${s.signaux_couverts}/${s.signaux_total}`, "Signaux clés repris"), kpi(duree(s.latence_mediane_ms), "Latence médiane"), kpi(cout, s.cout_projete ? "Coût par fiche (projeté*)" : "Coût par fiche")),
        s.corrections.length || s.defauts_format.length || s.remises_hors_regle || s.taux_repli_pct
            ? h("ul", { classe: "petit", attrs: { style: "margin-top:10px" } }, s.taux_repli_pct ? h("li", null, `IA en échec, fiche en repli : ${s.taux_repli_pct} %`) : null, s.corrections.map((c) => h("li", null, `${LIBELLES.correction[c.type]} : ${c.nombre}`)), s.remises_hors_regle ? h("li", null, `Remises annoncées sans être proposées : ${s.remises_hors_regle}`) : null, s.defauts_format.map((d) => h("li", null, `${d.libelle} : ${d.nombre} fiche(s)`)))
            : h("p", { classe: "petit doux", attrs: { style: "margin:10px 0 0" } }, "Aucune correction, aucun défaut de format."),
    ]);
}
function pointsReleves(e) {
    const points = [
        ...(e.repli_force ? ["IA en échec : fiche rédigée en repli"] : []),
        ...e.corrections.map((c) => `${LIBELLES.correction[c.type]} — ${c.message}`),
        ...e.remises_hors_regle,
        ...e.signaux.filter((s) => !s.couvert).map((s) => `Signal non repris : ${s.libelle}`),
        ...e.controles_format.filter((c) => !c.reussi).map((c) => `${c.libelle} : ${c.detail}`),
    ];
    return points.length ? h("ul", { classe: "petit" }, points.map((p) => h("li", null, p))) : h("p", { classe: "petit doux" }, "Rien à signaler.");
}
function detailParClient(campagne) {
    const redacteurs = campagne.syntheses.map((s) => s.redacteur);
    const parClient = new Map();
    for (const e of campagne.fiches)
        parClient.set(e.client_id, [...(parClient.get(e.client_id) ?? []), e]);
    const lignes = [...parClient.values()].sort((a, b) => Math.min(...a.map((e) => e.score_global)) - Math.min(...b.map((e) => e.score_global)) || a[0].client_id.localeCompare(b[0].client_id));
    let tous = false;
    const liste = h("ul", { classe: "liste" });
    const rafraichir = () => {
        const visibles = tous ? lignes : lignes.filter((l) => l.some((e) => e.score_global < 100));
        remplacer(liste, visibles.length
            ? visibles.map((evaluations) => {
                const premiere = evaluations[0];
                return h("li", null, h("details", { classe: "regle" }, h("summary", null, h("span", { classe: "nom" }, `${premiere.client_id} · ${premiere.client_nom}`), h("span", { classe: "espace" }), redacteurs.map((r) => {
                    const e = evaluations.find((x) => x.redacteur === r);
                    return e ? badge(`${LIBELLES.modeLLM[r]} ${e.score_global}`, varianteScore(e.score_global)) : null;
                })), h("div", { classe: "grille deux", attrs: { style: "margin-top:8px" } }, evaluations.map((e) => h("div", null, h("div", { classe: "gras petit" }, `${LIBELLES.modeLLM[e.redacteur]} — fidélité ${e.score_fidelite}, couverture ${e.score_couverture}, format ${e.score_format}`), pointsReleves(e)))), h("a", { classe: "petit", attrs: { href: `#/clients/${encodeURIComponent(premiere.client_id)}` } }, "Ouvrir la fiche du client ›")));
            })
            : h("li", null, vide("Toutes les fiches obtiennent 100.")));
    };
    const bascule = h("label", { classe: "petit ligne" }, h("input", { attrs: { type: "checkbox" }, on: { change: (ev) => ((tous = ev.target.checked), rafraichir()) } }), "Afficher tous les clients");
    rafraichir();
    return carte("Détail par client", [h("div", { attrs: { style: "margin-bottom:8px" } }, bascule), liste], {
        compte: lignes.filter((l) => l.some((e) => e.score_global < 100)).length,
    });
}
function campagneDetaillee(campagne) {
    return h("div", { classe: "pile" }, h("div", { classe: "ligne petit doux" }, `Campagne n° ${campagne.id ?? "—"} du ${dateCourte(campagne.lancee_le)} à ${heure(campagne.lancee_le)} · prompt `, h("code", null, campagne.empreinte_prompt), ` · données « ${campagne.source} » · ${new Set(campagne.fiches.map((f) => f.client_id)).size} clients · ${duree(campagne.duree_ms)}`, h("span", { classe: "espace" }), campagne.id !== null ? h("a", { classe: "bouton discret", attrs: { href: api.labo.rapportEvaluation(campagne.id) } }, "Rapport Markdown ↓") : null), h("div", { classe: "comparaison" }, campagne.syntheses.map(carteSynthese)), campagne.syntheses.some((s) => s.cout_projete)
        ? h("p", { classe: "petit doux", attrs: { style: "margin:0" } }, "* Coût projeté : IA simulée, estimée au tarif du modèle imité (tarifs publics de l'API Anthropic).")
        : null, detailParClient(campagne));
}
function historique(campagnes, ouvrir) {
    if (!campagnes.length)
        return null;
    const chronologiques = [...campagnes].reverse();
    const redacteurIA = (c) => c.syntheses.find((s) => s.redacteur !== "repli");
    const avecIA = chronologiques.filter((c) => redacteurIA(c));
    return carte("Historique des évaluations", [
        avecIA.length > 1
            ? h("div", { attrs: { style: "margin-bottom:12px" } }, h("div", { classe: "petit doux", attrs: { style: "margin-bottom:8px" } }, "Score de l'IA par campagne, de la plus ancienne à la plus récente (date et version du prompt)"), barresHorizontales(avecIA.map((c) => {
                const s = redacteurIA(c);
                return { libelle: `${dateCourte(c.lancee_le)} ${heure(c.lancee_le)} · ${c.empreinte_prompt.slice(0, 6)}`, valeur: s.score_global, affichage: nombre(s.score_global) };
            }), 100))
            : null,
        h("div", { classe: "tableau-conteneur" }, h("table", { classe: "tableau" }, h("thead", null, h("tr", null, h("th", null, "Date"), h("th", null, "Prompt"), h("th", null, "Scores"), h("th", { classe: "nombre" }, "Coût"), h("th", null, ""))), h("tbody", null, campagnes.map((c) => {
            const cout = c.syntheses.reduce((t, s) => t + (s.cout_projete ? 0 : (s.cout_total_usd ?? 0)), 0);
            return h("tr", null, h("td", null, `${dateCourte(c.lancee_le)} ${heure(c.lancee_le)}`), h("td", null, h("code", null, c.empreinte_prompt)), h("td", null, c.syntheses.map((s) => [badge(`${LIBELLES.modeLLM[s.redacteur]} ${nombre(s.score_global)}`, varianteScore(s.score_global)), " "])), h("td", { classe: "nombre" }, cout ? dollars(cout) : "—"), h("td", null, h("button", { classe: "bouton discret", attrs: { type: "button" }, on: { click: () => ouvrir(c.id) } }, "Voir")));
        })))),
    ], { compte: campagnes.length });
}
function suiviEnCours(suivi) {
    const pct = suivi.total ? Math.round((100 * suivi.faites) / suivi.total) : 0;
    return h("div", { classe: "pile", attrs: { style: "gap:6px" } }, h("div", { classe: "ligne petit" }, h("span", { classe: "gras" }, "Évaluation en cours"), h("span", { classe: "espace" }), `${suivi.faites}/${suivi.total} fiches`), h("div", { classe: "jauge" }, h("span", { attrs: { style: `width:${pct}%` } })));
}
export const vueQualiteIA = async (cible, _parametres, contexte) => {
    const zoneLancement = h("div");
    const zoneCampagne = h("div");
    const zoneHistorique = h("div");
    const modes = contexte.session.modes_disponibles.map((m) => m.mode);
    const choix = new Set(modes);
    const afficherCampagne = async (id) => {
        remplacer(zoneCampagne, chargement("Chargement de la campagne…"));
        try {
            remplacer(zoneCampagne, campagneDetaillee(await api.labo.evaluation(id)));
        }
        catch (erreur) {
            remplacer(zoneCampagne, messageErreur(erreur));
        }
    };
    const chargerHistorique = async () => {
        const campagnes = await api.labo.evaluations();
        remplacer(zoneHistorique, historique(campagnes, (id) => void afficherCampagne(id).then(() => zoneCampagne.scrollIntoView({ behavior: "smooth" }))));
        const derniere = campagnes[0];
        if (derniere)
            await afficherCampagne(derniere.id);
        else
            remplacer(zoneCampagne, carte(null, vide("Aucune évaluation pour l'instant : lancez la première ci-dessus.")));
    };
    const formulaire = () => h("div", { classe: "ligne" }, modes.map((mode) => h("label", { classe: "puce" }, h("input", {
        attrs: { type: "checkbox", checked: choix.has(mode) },
        on: { change: (ev) => (ev.target.checked ? choix.add(mode) : choix.delete(mode)) },
    }), ` ${LIBELLES.modeLLM[mode]}`)), h("span", { classe: "espace" }), bouton("Lancer l'évaluation", lancer, "principal"));
    const suivre = async () => {
        if (!cible.isConnected)
            return; // l'utilisateur a quitté la page
        const suivi = await api.labo.suiviEvaluation();
        if (suivi?.etat === "en_cours") {
            remplacer(zoneLancement, suiviEnCours(suivi));
            window.setTimeout(() => void suivre(), INTERVALLE_SUIVI_MS);
            return;
        }
        remplacer(zoneLancement, formulaire(), suivi?.etat === "echouee" ? messageErreur(`Évaluation interrompue : ${suivi.erreur ?? "erreur inconnue"}`) : null);
        if (suivi?.etat === "terminee")
            await chargerHistorique();
    };
    async function lancer() {
        if (!choix.size) {
            remplacer(zoneLancement, formulaire(), messageErreur("Choisissez au moins un rédacteur."));
            return;
        }
        try {
            remplacer(zoneLancement, suiviEnCours(await api.labo.lancerEvaluation({ redacteurs: modes.filter((m) => choix.has(m)), clients: null })));
            window.setTimeout(() => void suivre(), INTERVALLE_SUIVI_MS);
        }
        catch (erreur) {
            remplacer(zoneLancement, formulaire(), messageErreur(erreur));
        }
    }
    remplacer(cible, ongletsLabo("qualite"), titrePage("Qualité IA", "Chaque client, chaque rédacteur : fidélité aux données, signaux clés repris, format utilisable au téléphone"), h("div", { classe: "pile" }, carte("Lancer une évaluation", [h("p", { classe: "petit doux", attrs: { style: "margin:0 0 10px" } }, "Les fiches sont rédigées hors cache : celles des télévendeurs ne changent pas. Avec Claude, chaque fiche est facturée."), zoneLancement]), zoneCampagne, zoneHistorique));
    remplacer(zoneLancement, chargement("Chargement…"));
    try {
        // Une campagne lancée avant d'arriver sur la page est reprise là où elle en est.
        if ((await api.labo.suiviEvaluation())?.etat === "en_cours")
            void suivre();
        else
            remplacer(zoneLancement, formulaire());
        await chargerHistorique();
    }
    catch (erreur) {
        remplacer(zoneCampagne, messageErreur(erreur));
    }
};
