// Point d'entrée : session, en-tête, navigation et routage des vues.

import { api, ErreurApi, EVENEMENT_SESSION_EXPIREE } from "./api.js";
import { badge, messageErreur } from "./composants.js";
import { h, remplacer } from "./dom.js";
import { dateLongue } from "./format.js";
import { preferences } from "./preferences.js";
import { type Contexte, type Rubrique, Routeur } from "./routeur.js";
import type { ContexteSession, Permission, Role } from "./types-api.js";
import { vueClient360 } from "./vues/client360.js";
import { vueClients } from "./vues/clients.js";
import { afficherConnexion } from "./vues/connexion.js";
import { vueFiche } from "./vues/fiche.js";
import { vueFileAppels } from "./vues/file-appels.js";
import { vueLabo } from "./vues/labo.js";
import { vueStock } from "./vues/stock.js";
import { vueTableauDeBord } from "./vues/tableau-de-bord.js";

interface EntreeMenu {
  rubrique: Rubrique;
  chemin: string;
  icone: string;
  libelle: string;
  permission?: Permission;
}

const MENU: EntreeMenu[] = [
  { rubrique: "appels", chemin: "#/", icone: "📞", libelle: "Appels" },
  { rubrique: "clients", chemin: "#/clients", icone: "👥", libelle: "Clients" },
  { rubrique: "stock", chemin: "#/stock", icone: "📦", libelle: "Stock" },
  { rubrique: "tableau", chemin: "#/tableau-de-bord", icone: "📊", libelle: "Suivi" },
  { rubrique: "labo", chemin: "#/labo", icone: "🧪", libelle: "Labo", permission: "utiliser_le_labo" },
];

const LIBELLES_ROLES: Record<Role, string> = { televendeur: "Télévendeur", responsable: "Responsable", admin: "Administrateur" };

const routeur = new Routeur()
  .ajouter("/", "appels", vueFileAppels)
  .ajouter("/clients", "clients", vueClients)
  .ajouter("/clients/:id", "clients", vueFiche)
  .ajouter("/clients/:id/360", "clients", vueClient360)
  .ajouter("/stock", "stock", vueStock)
  .ajouter("/tableau-de-bord", "tableau", vueTableauDeBord)
  .ajouter("/labo", "labo", vueLabo);

function entete(contexte: Contexte, auChangementVendeur: () => void, seDeconnecter: () => void) {
  const { session } = contexte;
  // Seuls les responsables choisissent la file affichée ; un télévendeur voit toujours la sienne.
  const filtre = contexte.peut("voir_toutes_les_files")
    ? h(
        "select",
        {
          attrs: { "aria-label": "File d'appels affichée" },
          on: {
            change: (e) => {
              preferences.televendeur = (e.target as HTMLSelectElement).value || null;
              auChangementVendeur();
            },
          },
        },
        h("option", { attrs: { value: "" } }, "Tous les télévendeurs"),
        session.televendeurs.map((nom) => h("option", { attrs: { value: nom, selected: nom === preferences.televendeur } }, nom)),
      )
    : null;
  return h(
    "header",
    { classe: "entete" },
    h(
      "div",
      { classe: "entete-contenu" },
      h(
        "div",
        { attrs: { style: "flex:1;min-width:0" } },
        h("h1", null, "Copilote télévente"),
        h("div", { classe: "sous" }, `${dateLongue(session.date_du_jour)} · données ${session.source_donnees}`),
      ),
      filtre,
      h(
        "div",
        { classe: "utilisateur" },
        h("span", { classe: "nom-utilisateur" }, session.utilisateur.nom_affiche),
        h("span", { classe: "role-utilisateur" }, LIBELLES_ROLES[session.utilisateur.role]),
      ),
      session.authentification
        ? h("button", { classe: "bouton-entete", attrs: { type: "button", title: "Se déconnecter" }, on: { click: seDeconnecter } }, "Quitter")
        : null,
    ),
  );
}

function navigation(contexte: Contexte): HTMLElement {
  return h(
    "nav",
    { classe: "navigation", attrs: { "aria-label": "Navigation principale" } },
    MENU.filter((m) => !m.permission || contexte.peut(m.permission)).map((m) =>
      h(
        "a",
        { attrs: { href: m.chemin, "data-rubrique": m.rubrique } },
        h("span", { classe: "icone", attrs: { "aria-hidden": "true" } }, m.icone),
        m.rubrique === "tableau" && !contexte.peut("voir_statistiques_globales") ? "Mes résultats" : m.libelle,
      ),
    ),
  );
}

function lancerApplication(racine: HTMLElement, session: ContexteSession): void {
  const principal = h("main", { attrs: { id: "contenu" } });
  const contexte: Contexte = {
    session,
    naviguer: (chemin) => (window.location.hash = `#${chemin}`),
    peut: (permission) => session.permissions.includes(permission),
  };
  const nav = navigation(contexte);

  const afficher = (): void => {
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
    if (resolution.route.rubrique === "labo" && !contexte.peut("utiliser_le_labo")) {
      remplacer(cible, messageErreur("Cette page est réservée aux responsables."));
      return;
    }
    void resolution.route.vue(cible, resolution.parametres, contexte);
  };

  const seDeconnecter = async (): Promise<void> => {
    await api.deconnexion().catch(() => undefined);
    window.location.hash = "#/";
    window.location.reload();
  };

  remplacer(
    racine,
    entete(contexte, afficher, () => void seDeconnecter()),
    nav,
    principal,
    session.authentification ? null : h("div", { classe: "bandeau-dev" }, badge("Authentification désactivée (poste de développement)", "attention")),
  );
  window.addEventListener("hashchange", afficher);
  afficher();
}

async function demarrer(): Promise<void> {
  const racine = document.getElementById("application");
  if (!racine) return;
  try {
    lancerApplication(racine, await api.session());
  } catch (erreur) {
    if (erreur instanceof ErreurApi && erreur.statut === 401) {
      afficherConnexion(racine, () => window.location.reload());
      return;
    }
    remplacer(racine, h("main", null, messageErreur(erreur)));
  }
}

// Session expirée en cours d'utilisation : retour à la page de connexion.
window.addEventListener(EVENEMENT_SESSION_EXPIREE, () => window.location.reload());

void demarrer();
