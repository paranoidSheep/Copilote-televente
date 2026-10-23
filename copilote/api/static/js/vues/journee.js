// La journée du télévendeur : objectifs, agenda des rappels, tournée et export des commandes.
import { api } from "../api.js";
import { badge, carte, chargement, kpi, messageErreur, titrePage, vide } from "../composants.js";
import { h, remplacer } from "../dom.js";
import { dateCourte, euros, nombre } from "../format.js";
import { preferences } from "../preferences.js";
export const lienFiche = (clientId, tournee = false) => `#/clients/${encodeURIComponent(clientId)}${tournee ? "?tournee=1" : ""}`;
/** File affichée : la sienne pour un télévendeur, celle choisie dans l'en-tête pour un responsable. */
export const filtreTelevendeur = (contexte) => contexte.peut("voir_toutes_les_files") ? (preferences.televendeur ?? undefined) : undefined;
function jaugeObjectif(libelle, objectif, affichage) {
    const atteint = objectif.pct >= 100;
    return h("div", { classe: "objectif" }, h("div", { classe: "ligne" }, h("span", { classe: "gras" }, libelle), h("span", { classe: "espace" }), h("span", { classe: "nombre" }, `${affichage(objectif.realise)} / ${affichage(objectif.cible)}`)), h("div", { classe: `jauge ${atteint ? "atteint" : ""}`.trim() }, h("span", { attrs: { style: `width:${Math.min(100, objectif.pct)}%` } })), h("div", { classe: "meta" }, atteint ? "Objectif atteint ✓" : `${objectif.pct} % de l'objectif`));
}
export function objectifsDuJour(journee) {
    const o = journee.objectifs;
    return h("div", { classe: "grille deux" }, jaugeObjectif("Appels", o.appels, (v) => nombre(v)), jaugeObjectif("CA accepté HT", o.ca_accepte_ht, (v) => euros(v).replace(",00", "")));
}
/** Étape qui suit le client courant dans la tournée (en reprenant au début si besoin). */
export function etapeSuivante(tournee, clientCourant) {
    const etapes = tournee.etapes;
    const position = clientCourant === null ? -1 : etapes.findIndex((e) => e.client_id === clientCourant);
    const apres = [...etapes.slice(position + 1), ...etapes.slice(0, Math.max(0, position))];
    return apres.find((e) => !e.fait && e.client_id !== clientCourant) ?? null;
}
export function boutonTournee(tournee) {
    if (!tournee.total)
        return null;
    if (!tournee.prochain)
        return h("a", { classe: "bouton", attrs: { href: "#/tournee/fin" } }, "Tournée terminée ✓ · bilan");
    const libelle = tournee.faits ? `Reprendre la tournée · ${tournee.faits}/${tournee.total}` : "Démarrer la tournée";
    return h("a", { classe: "bouton principal", attrs: { href: lienFiche(tournee.prochain.client.id, true) } }, `▶ ${libelle}`);
}
export function lienExport(televendeur) {
    return h("a", { classe: "bouton", attrs: { href: api.exportCommandes(televendeur), download: "" } }, "⬇ Commandes du jour (CSV)");
}
export function carteMaJournee(journee, televendeur) {
    const t = journee.tournee;
    return carte(journee.televendeur === null ? "Journée de l'équipe" : "Ma journée", [
        objectifsDuJour(journee),
        h("div", { classe: "ligne", attrs: { style: "margin-top:12px" } }, boutonTournee(t), lienExport(televendeur), h("span", { classe: "espace" }), h("span", { classe: "petit doux" }, `${journee.objectifs.commandes} commande(s) · ${t.faits}/${t.total} clients appelés`)),
    ], { classe: "journee" });
}
function entreeAgenda(e) {
    const quand = e.statut === "en_retard" ? badge(`en retard de ${-e.ecart_jours} j`, "alerte") : e.statut === "aujourdhui" ? badge("aujourd'hui", "attention") : badge(dateCourte(e.rappel_le), "info");
    return h("li", null, h("div", { classe: "entree" }, h("a", { classe: "nom", attrs: { href: lienFiche(e.client.id) } }, e.client.nom), quand), h("div", { classe: "meta" }, `${e.client.contact} · ${e.client.telephone} · demandé le ${dateCourte(e.demande_le)} par ${e.demande_par}`), e.notes ? h("div", { classe: "argument" }, e.notes) : null);
}
export function carteAgenda(agenda) {
    const total = agenda.en_retard.length + agenda.aujourdhui.length + agenda.a_venir.length;
    const groupe = (titre, entrees) => entrees.length ? [h("div", { classe: "sous-titre" }, titre), h("ul", { classe: "liste" }, entrees.map(entreeAgenda))] : null;
    return carte("Agenda des rappels", total
        ? [groupe("En retard", agenda.en_retard), groupe("Aujourd'hui", agenda.aujourdhui), groupe("À venir", agenda.a_venir)]
        : vide("Aucun rappel promis en attente."), { compte: total });
}
/** Bandeau affiché au-dessus de la fiche pendant la tournée. */
export function bandeauTournee(tournee, clientCourant) {
    const suivante = etapeSuivante(tournee, clientCourant);
    const pct = tournee.total ? Math.round((100 * tournee.faits) / tournee.total) : 0;
    return h("section", { classe: "carte bandeau-tournee" }, h("div", { classe: "ligne" }, h("span", { classe: "gras" }, `Tournée · ${tournee.faits}/${tournee.total} appels`), h("span", { classe: "espace" }), suivante ? h("a", { classe: "bouton discret", attrs: { href: lienFiche(suivante.client_id, true) } }, `Passer ce client › ${suivante.nom}`) : null, h("a", { classe: "bouton discret", attrs: { href: "#/" } }, "Quitter la tournée")), h("div", { classe: "jauge" }, h("span", { attrs: { style: `width:${pct}%` } })));
}
/** Après le compte-rendu, pendant la tournée : le client suivant, ou le bilan. */
export function suiteTournee(tournee, clientCourant) {
    const suivante = etapeSuivante(tournee, clientCourant);
    return suivante ? { libelle: `Client suivant : ${suivante.nom} ›`, lien: lienFiche(suivante.client_id, true) } : { libelle: "Terminer la tournée ›", lien: "#/tournee/fin" };
}
export const vueFinTournee = async (cible, _parametres, contexte) => {
    remplacer(cible, chargement("Bilan de la tournée…"));
    const televendeur = filtreTelevendeur(contexte);
    let journee;
    try {
        journee = await api.journee(televendeur);
    }
    catch (erreur) {
        remplacer(cible, messageErreur(erreur));
        return;
    }
    const o = journee.objectifs;
    const restants = journee.tournee.total - journee.tournee.faits;
    remplacer(cible, titrePage(restants ? "Bilan de la tournée en cours" : "Tournée terminée", `${journee.tournee.faits} clients appelés sur ${journee.tournee.total}`), h("div", { classe: "pile" }, h("div", { classe: "kpis" }, kpi(nombre(o.appels.realise), "Appels du jour"), kpi(o.commandes, "Commandes"), kpi(euros(o.ca_accepte_ht.realise), "CA accepté HT"), kpi(o.taux_transformation_pct === null ? "—" : `${o.taux_transformation_pct} %`, "Transformation")), carte("Objectifs du jour", objectifsDuJour(journee)), carte("Saisie dans l'ERP", [
        h("p", { classe: "petit", attrs: { style: "margin:0 0 10px" } }, "Toutes les commandes acceptées aujourd'hui, prêtes à saisir ou à importer dans l'ERP (tableur, séparateur « ; »)."),
        h("div", { classe: "ligne" }, lienExport(televendeur), restants ? boutonTournee(journee.tournee) : null, h("a", { classe: "bouton discret", attrs: { href: "#/" } }, "Retour à la file d'appels")),
    ]), carteAgenda(journee.agenda)));
};
