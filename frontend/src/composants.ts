// Composants d'interface réutilisables (fonctions pures qui renvoient des nœuds DOM).

import { type Enfant, h, s } from "./dom.js";
import { LIBELLES, nombre } from "./format.js";
import type { EtapeTrace, TraceExecution } from "./types-api.js";

export type Variante = "primaire" | "alerte" | "attention" | "info" | "succes" | "neutre";

export function carte(titre: string | null, contenu: Enfant, options: { classe?: string; compte?: number } = {}) {
  return h(
    "section",
    { classe: `carte ${options.classe ?? ""}`.trim() },
    titre === null ? null : h("h3", null, titre, options.compte === undefined ? null : h("span", { classe: "compte" }, options.compte)),
    contenu,
  );
}

export function repliable(titre: Enfant, contenu: Enfant, ouvert = false) {
  return h("details", { classe: "carte", attrs: { open: ouvert } }, h("summary", null, titre), contenu);
}

export function badge(texte: string, variante: Variante = "neutre") {
  return h("span", { classe: `badge ${variante === "neutre" ? "" : variante}`.trim() }, texte);
}

export function kpi(valeur: Enfant, libelle: string, classe = "") {
  return h("div", { classe: "kpi" }, h("div", { classe: `valeur ${classe}`.trim() }, valeur), h("div", { classe: "libelle" }, libelle));
}

export function chargement(message: string, detail?: string) {
  return h("div", { classe: "chargement" }, h("div", { classe: "rond" }), message, detail ? h("div", { classe: "petit" }, detail) : null);
}

export function messageErreur(erreur: unknown) {
  const texte = erreur instanceof Error ? erreur.message : String(erreur);
  return h("p", { classe: "message-erreur", attrs: { role: "alert" } }, texte);
}

export function vide(message: string) {
  return h("p", { classe: "vide" }, message);
}

export function titrePage(titre: string, detail?: Enfant, actions?: Enfant) {
  return h(
    "div",
    { classe: "titre-page" },
    h("div", null, h("h2", null, titre), detail ? h("div", { classe: "detail" }, detail) : null),
    actions ?? null,
  );
}

export function bouton(texte: string, action: () => void | Promise<void>, classe = "") {
  const element = h("button", { classe: `bouton ${classe}`.trim(), attrs: { type: "button" } }, texte);
  element.addEventListener("click", async () => {
    element.disabled = true;
    try {
      await action();
    } finally {
      element.disabled = false;
    }
  });
  return element;
}

export function boutonCopier(texte: () => string, libelle = "Copier") {
  const element = h("button", { classe: "bouton", attrs: { type: "button" } }, libelle);
  element.addEventListener("click", async () => {
    try {
      await navigator.clipboard.writeText(texte());
      element.textContent = "Copié ✓";
    } catch {
      element.textContent = "Copie impossible";
    }
    window.setTimeout(() => (element.textContent = libelle), 2000);
  });
  return element;
}

export function variationClasse(valeur: number | null | undefined): string {
  if (valeur === null || valeur === undefined) return "";
  return valeur >= 0 ? "hausse" : "baisse";
}

/** Barres horizontales (répartition, taux) : libellé, piste proportionnelle, valeur. */
export function barresHorizontales(lignes: { libelle: string; valeur: number; affichage: string }[], maximum?: number) {
  const max = maximum ?? Math.max(1, ...lignes.map((l) => l.valeur));
  return h(
    "div",
    { classe: "barres-h" },
    lignes.map((l) =>
      h(
        "div",
        { classe: "rang" },
        h("span", null, l.libelle),
        h("span", { classe: "piste" }, h("span", { attrs: { style: `width:${Math.round((l.valeur / max) * 100)}%` } })),
        h("span", { classe: "nombre petit" }, l.affichage),
      ),
    ),
  );
}

/** Histogramme vertical en SVG, sans dépendance. */
export function histogramme(donnees: { libelle: string; valeur: number; info: string }[], hauteur = 160) {
  const largeurBarre = 28;
  const ecart = 10;
  const marge = 18;
  // Largeur minimale : avec peu de barres, le graphique reste à l'échelle au lieu de s'étirer.
  const largeur = Math.max(420, donnees.length * (largeurBarre + ecart) + ecart);
  const decalage = (largeur - (donnees.length * (largeurBarre + ecart) + ecart)) / 2;
  const max = Math.max(1, ...donnees.map((d) => d.valeur));
  return s(
    "svg",
    { class: "graphique", viewBox: `0 0 ${largeur} ${hauteur + marge}`, role: "img" },
    donnees.map((d, i) => {
      const hauteurBarre = Math.max(2, (d.valeur / max) * (hauteur - 14));
      const x = decalage + ecart + i * (largeurBarre + ecart);
      return s(
        "g",
        {},
        s("rect", { class: "barre-graph", x, y: hauteur - hauteurBarre, width: largeurBarre, height: hauteurBarre, rx: 4 }, s("title", {}, d.info)),
        s("text", { x: x + largeurBarre / 2, y: hauteur + 12, "text-anchor": "middle" }, d.libelle),
      );
    }),
  );
}

function etapeTrace(etape: EtapeTrace) {
  const jetons =
    etape.jetons_entree !== null && etape.jetons_sortie !== null
      ? ` · ${nombre(etape.jetons_entree)} → ${nombre(etape.jetons_sortie)} jetons`
      : "";
  return h(
    "div",
    { classe: `etape ${etape.erreur ? "erreur" : ""}`.trim() },
    h("span", { classe: "type", attrs: { title: etape.type } }, LIBELLES.etape[etape.type]),
    h("span", { classe: "resume" }, etape.resume, h("span", { classe: "doux petit" }, jetons)),
    h("span", { classe: "duree petit" }, `${etape.duree_ms} ms`),
    etape.detail ? h("pre", { classe: "code" }, etape.detail) : null,
  );
}

/** Déroulé de la rédaction par l'IA : appels au modèle et aux outils. */
export function traceExecution(trace: TraceExecution) {
  const entree = trace.etapes.reduce((t, e) => t + (e.jetons_entree ?? 0), 0);
  const sortie = trace.etapes.reduce((t, e) => t + (e.jetons_sortie ?? 0), 0);
  return h(
    "div",
    { classe: "pile" },
    h(
      "div",
      { classe: "ligne petit doux" },
      badge(trace.fournisseur, "info"),
      trace.modele,
      `· ${trace.etapes.length} étapes · ${trace.duree_totale_ms} ms · ${nombre(entree)} jetons lus, ${nombre(sortie)} écrits`,
    ),
    h("div", { classe: "trace" }, trace.etapes.map(etapeTrace)),
  );
}
