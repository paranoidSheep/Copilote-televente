// Laboratoire : voir ce que l'IA voit (prompt, outils, résultats bruts) et comparer les rédacteurs.
import { api } from "../api.js";
import { badge, bouton, carte, chargement, messageErreur, repliable, titrePage, traceExecution } from "../composants.js";
import { h, remplacer } from "../dom.js";
import { euros, LIBELLES } from "../format.js";
import { ongletsLabo } from "./onglets-labo.js";
const json = (valeur) => JSON.stringify(valeur, null, 2);
function colonneFiche(mode, fiche) {
    return carte(LIBELLES.modeLLM[mode], [
        h("p", { classe: "petit doux", attrs: { style: "margin:0 0 8px" } }, badge(LIBELLES.modeFiche[fiche.mode], fiche.mode === "repli" ? "attention" : "info"), " ", fiche.modele ?? "", fiche.avertissement ? ` — ${fiche.avertissement}` : ""),
        h("p", { classe: "petit" }, fiche.resume_habitudes),
        h("div", { classe: "gras petit" }, "Accroches"),
        h("ol", { classe: "petit" }, fiche.accroches.map((a) => h("li", null, a))),
        h("div", { classe: "gras petit" }, "Stock proposé"),
        h("ul", { classe: "petit" }, fiche.stock_a_ecouler.map((s) => h("li", null, `${s.libelle} : −${s.remise_pct} % (${euros(s.prix_propose_ht)})`))),
        h("div", { classe: "petit doux" }, `Panier proposé : ${euros(fiche.panier.total_ht)} HT · ${fiche.garde_fous.length} correction(s) automatique(s)`),
        fiche.trace ? h("div", { attrs: { style: "margin-top:10px" } }, traceExecution(fiche.trace)) : null,
    ]);
}
export const vueLabo = async (cible, parametres, _contexte) => {
    remplacer(cible, chargement("Chargement du laboratoire…"));
    let clients;
    try {
        clients = await api.clients();
    }
    catch (erreur) {
        remplacer(cible, messageErreur(erreur));
        return;
    }
    const choixClient = h("select", { classe: "champ", attrs: { "aria-label": "Client" } }, clients.map((c) => h("option", { attrs: { value: c.id, selected: c.id === (parametres["client"] ?? "C001") } }, `${c.id} · ${c.nom}`)));
    const champProduit = h("input", { classe: "champ", attrs: { placeholder: "Code produit pour details_produit (ex. FR007)", value: parametres["produit"] ?? "" } });
    const zoneOutils = h("div", { classe: "pile" });
    const zoneComparaison = h("div");
    const zoneAgent = h("div");
    const executerOutils = async () => {
        remplacer(zoneOutils, chargement("Exécution des outils…"));
        try {
            const resultats = await api.labo.outils(choixClient.value, champProduit.value.trim() || undefined);
            remplacer(zoneOutils, resultats.map((r) => repliable([h("code", null, r.nom), " ", r.est_erreur ? badge("erreur", "alerte") : badge("ok", "succes")], h("pre", { classe: "code" }, typeof r.resultat === "string" ? r.resultat : json(r.resultat)))));
        }
        catch (erreur) {
            remplacer(zoneOutils, messageErreur(erreur));
        }
    };
    const comparer = async () => {
        remplacer(zoneComparaison, chargement("Génération avec chaque rédacteur…"));
        try {
            const fiches = await api.labo.comparaison(choixClient.value);
            remplacer(zoneComparaison, h("div", { classe: "comparaison" }, Object.entries(fiches).map(([mode, fiche]) => (fiche ? colonneFiche(mode, fiche) : null))));
        }
        catch (erreur) {
            remplacer(zoneComparaison, messageErreur(erreur));
        }
    };
    const afficherAgent = async () => {
        remplacer(zoneAgent, chargement("Chargement de la configuration…"));
        try {
            const agent = await api.labo.agent(choixClient.value);
            remplacer(zoneAgent, h("div", { classe: "pile" }, repliable("Prompt système", h("pre", { classe: "code" }, agent.prompt_systeme), true), repliable("Message initial", h("pre", { classe: "code" }, agent.exemple_demande)), agent.outils.map((o) => repliable([h("code", null, o.nom), " ", h("span", { classe: "doux petit" }, o.description)], h("pre", { classe: "code" }, json(o.schema_entree))))));
        }
        catch (erreur) {
            remplacer(zoneAgent, messageErreur(erreur));
        }
    };
    remplacer(cible, ongletsLabo("agent"), titrePage("Laboratoire", "Inspecter l'agent IA : ce qu'il voit, ce qu'il produit, et la comparaison des rédacteurs"), carte("Client à analyser", h("div", { classe: "formulaire" }, h("div", { classe: "colonnes" }, choixClient, champProduit), h("div", { classe: "ligne" }, bouton("Exécuter les outils", executerOutils, "principal"), bouton("Comparer les rédacteurs", comparer), bouton("Configuration de l'agent", afficherAgent), h("a", { classe: "bouton discret", attrs: { href: "/docs", target: "_blank", rel: "noopener" } }, "Documentation de l'API ↗")))), h("div", { attrs: { style: "height:12px" } }), zoneComparaison, h("div", { classe: "grille deux", attrs: { style: "margin-top:12px" } }, h("div", { classe: "pile" }, zoneOutils), h("div", { classe: "pile" }, zoneAgent)));
    await executerOutils();
};
