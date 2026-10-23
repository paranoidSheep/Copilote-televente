// Données : diagnostic de la source (connexion au datahub, contrat d'interface, qualité). Réservé aux responsables.
import { api } from "../api.js";
import { badge, bouton, carte, chargement, kpi, messageErreur, titrePage, vide } from "../composants.js";
import { h, remplacer } from "../dom.js";
import { dateCourte, heure, nombre } from "../format.js";
const STATUTS = {
    conforme: { libelle: "Conforme", variante: "succes", carte: "accent" },
    a_surveiller: { libelle: "À surveiller", variante: "attention", carte: "attention" },
    a_corriger: { libelle: "À corriger", variante: "alerte", carte: "alerte" },
    lecture_impossible: { libelle: "Lecture impossible", variante: "alerte", carte: "alerte" },
};
const GRAVITES = {
    critique: { libelle: "Critique", variante: "alerte" },
    alerte: { libelle: "Alerte", variante: "attention" },
    info: { libelle: "Info", variante: "info" },
};
const TRAITEMENTS = {
    ecarte: "écarté des analyses",
    signale: "à corriger dans l'ERP",
};
const secondes = (ms) => `${nombre(ms / 1000)} s`;
function bandeauStatut(rapport) {
    const statut = STATUTS[rapport.statut];
    return carte(null, [
        h("div", { classe: "ligne" }, h("span", { classe: "statut-diagnostic" }, badge(statut.libelle, statut.variante)), h("span", { classe: "gras" }, rapport.resume)),
        h("div", { classe: "meta", attrs: { style: "margin-top:8px" } }, `Source « ${rapport.source} » · date de référence ${dateCourte(rapport.date_reference)} · ${rapport.periode_analyse_jours} jours d'historique analysés · `, `diagnostic de ${heure(rapport.genere_le)} en ${secondes(rapport.duree_totale_ms)}`),
    ], { classe: statut.carte });
}
function volumes(rapport) {
    const v = rapport.volumes;
    if (!v)
        return null;
    return h("div", { classe: "kpis" }, kpi(nombre(v.clients), "Clients"), kpi(nombre(v.produits), "Produits au catalogue"), kpi(nombre(v.commandes), `Commandes (${nombre(v.lignes)} lignes)`), kpi(nombre(v.lots), "Lots en stock"));
}
function connexion(mesures) {
    const max = Math.max(1, ...mesures.map((m) => m.duree_ms));
    return carte("Connexion", h("div", { classe: "tableau-conteneur" }, h("table", { classe: "tableau" }, h("thead", null, h("tr", null, h("th", null, "Ressource"), h("th", { classe: "nombre" }, "Volume"), h("th", null, "Temps de réponse"))), h("tbody", null, mesures.map((m) => h("tr", null, h("td", null, m.libelle), h("td", { classe: "nombre" }, m.volume === null ? badge("erreur", "alerte") : nombre(m.volume)), h("td", null, m.erreur
        ? h("span", { classe: "petit ko" }, m.erreur)
        : h("div", { classe: "duree-mesure" }, h("span", { classe: "jauge" }, h("span", { attrs: { style: `width:${Math.max(3, Math.round((m.duree_ms / max) * 100))}%` } })), h("span", { classe: "petit nombre" }, `${m.duree_ms} ms`)))))))));
}
function contrat(verifications) {
    if (!verifications.length)
        return carte("Contrat d'interface", vide("Non vérifié : les données n'ont pas pu être lues."));
    const reussies = verifications.filter((v) => v.reussie).length;
    return carte("Contrat d'interface", h("ul", { classe: "verifications" }, verifications.map((v) => h("li", null, h("span", { classe: v.reussie ? "ok" : "ko", attrs: { "aria-label": v.reussie ? "respecté" : "non respecté" } }, v.reussie ? "✓" : "✗"), h("div", null, h("div", null, v.libelle), h("div", { classe: "meta" }, v.detail))))), reussies === verifications.length ? {} : { compte: verifications.length - reussies });
}
function regle(r) {
    const gravite = GRAVITES[r.gravite];
    const restants = r.nombre - r.exemples.length;
    return h("li", null, h("details", { classe: "regle" }, h("summary", null, badge(gravite.libelle, gravite.variante), h("span", { classe: "nom" }, r.libelle), h("span", { classe: "espace" }), h("span", { classe: "puce" }, TRAITEMENTS[r.traitement]), h("span", { classe: "compte-regle nombre" }, nombre(r.nombre))), h("p", { classe: "petit", attrs: { style: "margin:8px 0" } }, r.impact), h("table", { classe: "tableau" }, h("tbody", null, r.exemples.map((e) => h("tr", null, h("td", null, h("code", null, e.identifiant)), h("td", null, e.detail))))), restants > 0 ? h("p", { classe: "meta" }, `… et ${nombre(restants)} autre${restants > 1 ? "s" : ""}`) : null));
}
function qualite(regles) {
    if (!regles.length)
        return null;
    const enDefaut = regles.filter((r) => r.nombre > 0);
    const conformes = regles.filter((r) => r.nombre === 0);
    return h("div", { classe: "pile" }, carte("Qualité des données", enDefaut.length ? h("ul", { classe: "liste" }, enDefaut.map(regle)) : vide("Aucune anomalie détectée."), { compte: enDefaut.length }), conformes.length
        ? carte(`Contrôles sans anomalie (${conformes.length}/${regles.length})`, h("ul", { classe: "verifications compactes" }, conformes.map((r) => h("li", null, h("span", { classe: "ok" }, "✓"), h("div", null, r.libelle)))))
        : null);
}
export const vueDonnees = async (cible) => {
    const afficher = async () => {
        remplacer(cible, chargement("Diagnostic en cours…", "Lecture complète de la source, sans cache"));
        let rapport;
        try {
            rapport = await api.diagnostic();
        }
        catch (erreur) {
            remplacer(cible, messageErreur(erreur));
            return;
        }
        remplacer(cible, titrePage("Données", "Connexion au datahub, contrat d'interface et qualité des données ERP", bouton("Relancer le diagnostic", afficher)), h("div", { classe: "pile" }, bandeauStatut(rapport), volumes(rapport), h("div", { classe: "grille deux" }, connexion(rapport.connexion), contrat(rapport.contrat)), qualite(rapport.qualite)));
    };
    await afficher();
};
