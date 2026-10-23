// Routage par fragment d'URL (#/…) : aucune configuration serveur nécessaire.

import type { ContexteSession, Permission } from "./types-api.js";

export interface Contexte {
  session: ContexteSession;
  /** Navigue vers un chemin de l'application (ex. « /tableau-de-bord?jours=7 »). */
  naviguer: (chemin: string) => void;
  peut: (permission: Permission) => boolean;
}

export type Vue = (cible: HTMLElement, parametres: Record<string, string>, contexte: Contexte) => Promise<void>;

export type Rubrique = "appels" | "clients" | "stock" | "tableau" | "labo" | "donnees";

interface Route {
  motif: RegExp;
  noms: readonly string[];
  rubrique: Rubrique;
  vue: Vue;
}

export class Routeur {
  private readonly routes: Route[] = [];

  ajouter(chemin: string, rubrique: Rubrique, vue: Vue): this {
    const noms: string[] = [];
    const motif = new RegExp(
      "^" +
        chemin.replace(/:([a-z_]+)/g, (_tout, nom: string) => {
          noms.push(nom);
          return "([^/]+)";
        }) +
        "$",
    );
    this.routes.push({ motif, noms, rubrique, vue });
    return this;
  }

  resoudre(fragment: string): { route: Route; parametres: Record<string, string> } | null {
    const [chemin = "/", requete = ""] = fragment.replace(/^#/, "").split("?");
    const parametres: Record<string, string> = Object.fromEntries(new URLSearchParams(requete));
    for (const route of this.routes) {
      const correspondance = route.motif.exec(chemin || "/");
      if (correspondance) {
        route.noms.forEach((nom, i) => (parametres[nom] = decodeURIComponent(correspondance[i + 1] ?? "")));
        return { route, parametres };
      }
    }
    return null;
  }
}
