// Point d'entrée : en-tête, navigation et routage des vues.
import { api } from "./api.js";
import { messageErreur } from "./composants.js";
import { h, remplacer } from "./dom.js";
import { dateLongue } from "./format.js";
import { preferences } from "./preferences.js";
import { Routeur } from "./routeur.js";
import { vueClient360 } from "./vues/client360.js";
import { vueClients } from "./vues/clients.js";
import { vueFiche } from "./vues/fiche.js";
import { vueFileAppels } from "./vues/file-appels.js";
import { vueLabo } from "./vues/labo.js";
import { vueStock } from "./vues/stock.js";
import { vueTableauDeBord } from "./vues/tableau-de-bord.js";
const RUBRIQUES = [
    { rubrique: "appels", chemin: "#/", icone: "📞", libelle: "Appels" },
    { rubrique: "clients", chemin: "#/clients", icone: "👥", libelle: "Clients" },
    { rubrique: "stock", chemin: "#/stock", icone: "📦", libelle: "Stock" },
    { rubrique: "tableau", chemin: "#/tableau-de-bord", icone: "📊", libelle: "Suivi" },
    { rubrique: "labo", chemin: "#/labo", icone: "🧪", libelle: "Labo" },
];
const routeur = new Routeur()
    .ajouter("/", "appels", vueFileAppels)
    .ajouter("/clients", "clients", vueClients)
    .ajouter("/clients/:id", "clients", vueFiche)
    .ajouter("/clients/:id/360", "clients", vueClient360)
    .ajouter("/stock", "stock", vueStock)
    .ajouter("/tableau-de-bord", "tableau", vueTableauDeBord)
    .ajouter("/labo", "labo", vueLabo);
function entete(sante, auChangementVendeur) {
    const choix = h("select", {
        attrs: { "aria-label": "Télévendeur" },
        on: {
            change: (e) => {
                preferences.televendeur = e.target.value || null;
                auChangementVendeur();
            },
        },
    }, h("option", { attrs: { value: "" } }, "Tous les télévendeurs"), sante.televendeurs.map((nom) => h("option", { attrs: { value: nom, selected: nom === preferences.televendeur } }, nom)));
    return h("header", { classe: "entete" }, h("div", { classe: "entete-contenu" }, h("div", { attrs: { style: "flex:1;min-width:0" } }, h("h1", null, "Copilote télévente"), h("div", { classe: "sous" }, `${dateLongue(sante.date_du_jour)} · données ${sante.source_donnees}`)), choix));
}
function navigation() {
    return h("nav", { classe: "navigation", attrs: { "aria-label": "Navigation principale" } }, RUBRIQUES.map((r) => h("a", { attrs: { href: r.chemin, "data-rubrique": r.rubrique } }, h("span", { classe: "icone", attrs: { "aria-hidden": "true" } }, r.icone), r.libelle)));
}
async function demarrer() {
    const racine = document.getElementById("application");
    if (!racine)
        return;
    let sante;
    try {
        sante = await api.sante();
    }
    catch (erreur) {
        remplacer(racine, h("main", null, messageErreur(erreur)));
        return;
    }
    const principal = h("main", { attrs: { id: "contenu" } });
    const nav = navigation();
    const contexte = { sante, naviguer: (chemin) => (window.location.hash = `#${chemin}`) };
    const afficher = () => {
        const resolution = routeur.resoudre(window.location.hash || "#/");
        for (const lien of nav.querySelectorAll("a")) {
            lien.classList.toggle("actif", lien.dataset["rubrique"] === resolution?.route.rubrique);
        }
        // Chaque affichage écrit dans son propre conteneur : une vue lente qui se termine
        // après une navigation n'écrase pas la vue suivante.
        const cible = h("div");
        remplacer(principal, cible);
        window.scrollTo(0, 0);
        document.title = "Copilote télévente";
        if (!resolution) {
            remplacer(cible, messageErreur("Page introuvable."));
            return;
        }
        void resolution.route.vue(cible, resolution.parametres, contexte);
    };
    remplacer(racine, entete(sante, afficher), nav, principal);
    window.addEventListener("hashchange", afficher);
    afficher();
}
void demarrer();
