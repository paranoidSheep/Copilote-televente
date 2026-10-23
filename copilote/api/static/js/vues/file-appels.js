// File d'appels du jour : les clients à appeler, du plus au moins prioritaire, avec les raisons.
import { api } from "../api.js";
import { badge, carte, chargement, kpi, messageErreur, titrePage, vide } from "../composants.js";
import { h, remplacer } from "../dom.js";
import { dateCourte, dateLongue, euros, LIBELLES } from "../format.js";
import { preferences } from "../preferences.js";
function tuile(appel) {
    const c = appel.client;
    return h("li", null, h("a", { classe: `tuile ${appel.deja_appele_aujourdhui ? "estompee" : ""}`.trim(), attrs: { href: `#/clients/${encodeURIComponent(c.id)}` } }, h("div", { classe: `score ${appel.niveau}`, attrs: { title: LIBELLES.niveau[appel.niveau] } }, h("div", { classe: "valeur" }, appel.score), h("div", { classe: "jauge" }, h("span", { attrs: { style: `width:${appel.score}%` } }))), h("div", { classe: "corps" }, h("div", { classe: "ligne" }, h("span", { classe: "titre" }, c.nom), appel.rappel_prevu ? badge(`Rappel ${dateCourte(appel.rappel_prevu)}`, "alerte") : null, appel.deja_appele_aujourdhui ? badge("Appelé aujourd'hui", "succes") : null), h("div", { classe: "meta" }, `${c.type} · ${c.ville} · ${c.contact} · panier ${euros(appel.panier_moyen_ht)}`), h("div", { classe: "puces", attrs: { style: "margin-top:6px" } }, appel.raisons.slice(0, 3).map((r) => h("span", { classe: "puce" }, r.libelle)))), h("span", { classe: "chevron" }, "›")));
}
export const vueFileAppels = async (cible) => {
    remplacer(cible, chargement("Calcul de la file d'appels…"));
    try {
        const file = await api.fileAppels(preferences.televendeur ?? undefined);
        const restants = file.appels.filter((a) => !a.deja_appele_aujourdhui);
        const hautes = restants.filter((a) => a.niveau === "haute").length;
        const appeles = file.appels.length - restants.length;
        remplacer(cible, titrePage("Appels du jour", `${dateLongue(file.date_du_jour)} · ${preferences.televendeur ?? "tous les télévendeurs"}`), h("div", { classe: "kpis", attrs: { style: "margin-bottom:12px" } }, kpi(restants.length, "Clients à appeler"), kpi(hautes, "Priorité haute", hautes ? "baisse" : ""), kpi(`${appeles} / ${file.appels.length}`, "Déjà appelés"), kpi(restants.filter((a) => a.rappel_prevu).length, "Rappels promis")), file.appels.length
            ? h("ul", { classe: "tuiles" }, file.appels.map(tuile))
            : carte(null, vide("Aucun client pour ce télévendeur.")), h("p", { classe: "pied" }, "Score sur 100 : rappel promis, jour de commande habituel, retards, produits décrochés, lots à DLC courte, poids du client, tendance."));
    }
    catch (erreur) {
        remplacer(cible, messageErreur(erreur));
    }
};
