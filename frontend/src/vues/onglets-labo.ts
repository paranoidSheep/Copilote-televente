// Navigation entre les pages du laboratoire.

import { h } from "../dom.js";

type PageLabo = "agent" | "qualite";

const PAGES: [PageLabo, string, string][] = [
  ["agent", "#/labo", "Agent et outils"],
  ["qualite", "#/labo/qualite", "Qualité IA"],
];

export function ongletsLabo(active: PageLabo): HTMLElement {
  return h(
    "nav",
    { classe: "onglets", attrs: { "aria-label": "Pages du laboratoire" } },
    PAGES.map(([page, chemin, libelle]) => h("a", { classe: page === active ? "actif" : "", attrs: { href: chemin } }, libelle)),
  );
}
