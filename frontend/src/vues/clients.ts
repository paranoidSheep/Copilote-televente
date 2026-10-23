// Liste des clients : recherche et filtre par type d'établissement.

import { api } from "../api.js";
import { chargement, messageErreur, titrePage, vide } from "../composants.js";
import { h, remplacer } from "../dom.js";
import { initiales } from "../format.js";
import type { Vue } from "../routeur.js";
import type { Client } from "../types-api.js";

export const vueClients: Vue = async (cible) => {
  remplacer(cible, chargement("Chargement des clients…"));
  let clients: Client[];
  try {
    clients = await api.clients();
  } catch (erreur) {
    remplacer(cible, messageErreur(erreur));
    return;
  }

  let recherche = "";
  let filtreType = "Tous";
  const types = ["Tous", ...new Set(clients.map((c) => c.type))];
  const liste = h("ul", { classe: "tuiles" });

  const rafraichir = (): void => {
    const q = recherche.trim().toLocaleLowerCase("fr");
    const visibles = clients.filter(
      (c) =>
        (filtreType === "Tous" || c.type === filtreType) &&
        (!q || `${c.nom} ${c.ville} ${c.contact} ${c.type}`.toLocaleLowerCase("fr").includes(q)),
    );
    remplacer(
      liste,
      visibles.length
        ? visibles.map((c) =>
            h(
              "li",
              null,
              h(
                "a",
                { classe: "tuile", attrs: { href: `#/clients/${encodeURIComponent(c.id)}` } },
                h("span", { classe: "avatar" }, initiales(c.nom)),
                h(
                  "span",
                  { classe: "corps" },
                  h("div", { classe: "titre" }, c.nom),
                  h("div", { classe: "meta" }, `${c.type} · ${c.ville} · ${c.contact} · ${c.commercial}`),
                ),
                h("span", { classe: "chevron" }, "›"),
              ),
            ),
          )
        : h("li", null, vide("Aucun client ne correspond.")),
    );
  };

  const onglets = h(
    "div",
    { classe: "onglets", attrs: { role: "tablist" } },
    types.map((type) =>
      h(
        "button",
        {
          classe: type === filtreType ? "actif" : "",
          attrs: { type: "button" },
          on: {
            click: (evenement) => {
              filtreType = type;
              for (const b of onglets.children) b.classList.toggle("actif", b === evenement.currentTarget);
              rafraichir();
            },
          },
        },
        type,
      ),
    ),
  );

  remplacer(
    cible,
    titrePage("Clients", `${clients.length} clients`),
    h("input", {
      classe: "champ",
      attrs: { type: "search", placeholder: "Rechercher un client, une ville, un contact…", "aria-label": "Rechercher" },
      on: {
        input: (evenement) => {
          recherche = (evenement.target as HTMLInputElement).value;
          rafraichir();
        },
      },
    }),
    h("div", { attrs: { style: "height:10px" } }),
    onglets,
    liste,
  );
  rafraichir();
};
