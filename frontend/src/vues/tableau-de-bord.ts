// Tableau de bord : efficacité des appels et des propositions du copilote.

import { api } from "../api.js";
import { barresHorizontales, carte, chargement, histogramme, kpi, messageErreur, titrePage, vide } from "../composants.js";
import { h, remplacer } from "../dom.js";
import { dateCourte, euros, LIBELLES, nombre, pourcentage } from "../format.js";
import type { Vue } from "../routeur.js";
import type { StatistiquesAppels } from "../types-api.js";

const PERIODES = [7, 30, 90] as const;

function contenu(stats: StatistiquesAppels) {
  if (!stats.nb_appels) return carte(null, vide("Aucun appel enregistré sur la période. Les comptes-rendus saisis depuis les fiches alimentent ce tableau de bord."));
  return [
    h(
      "div",
      { classe: "kpis", attrs: { style: "margin-bottom:12px" } },
      kpi(stats.nb_appels, `Appels (${stats.nb_clients} clients)`),
      kpi(pourcentage(stats.taux_transformation_pct), "Appels transformés en commande"),
      kpi(euros(stats.ca_accepte_ht), "CA accepté sur propositions"),
      kpi(nombre(stats.quantite_stock_ecoulee), "Unités de stock écoulées"),
    ),
    h(
      "div",
      { classe: "grille deux" },
      carte(
        "Taux d'acceptation des propositions",
        barresHorizontales(
          stats.par_origine.map((o) => ({
            libelle: `${LIBELLES.origine[o.origine]} (${o.acceptes}/${o.proposes})`,
            valeur: o.taux_acceptation_pct ?? 0,
            affichage: `${pourcentage(o.taux_acceptation_pct)} · ${euros(o.ca_accepte_ht)}`,
          })),
          100,
        ),
      ),
      carte(
        "Issues des appels",
        barresHorizontales(
          Object.entries(stats.issues).map(([issue, n]) => ({
            libelle: LIBELLES.issue[issue as keyof typeof LIBELLES.issue],
            valeur: n ?? 0,
            affichage: String(n ?? 0),
          })),
        ),
      ),
      carte(
        "CA accepté par jour",
        histogramme(stats.par_jour.map((j) => ({ libelle: dateCourte(j.jour), valeur: j.ca_accepte_ht, info: `${dateCourte(j.jour)} : ${j.appels} appels, ${euros(j.ca_accepte_ht)}` }))),
      ),
      carte(
        "Par télévendeur",
        h(
          "table",
          { classe: "tableau" },
          h("thead", null, h("tr", null, h("th", null, "Télévendeur"), h("th", { classe: "nombre" }, "Appels"), h("th", { classe: "nombre" }, "Commandes"), h("th", { classe: "nombre" }, "CA accepté"))),
          h(
            "tbody",
            null,
            stats.par_televendeur.map((t) =>
              h("tr", null, h("td", null, t.televendeur), h("td", { classe: "nombre" }, t.appels), h("td", { classe: "nombre" }, t.commandes), h("td", { classe: "nombre" }, euros(t.ca_accepte_ht))),
            ),
          ),
        ),
      ),
      carte(
        "Produits les plus acceptés",
        h(
          "table",
          { classe: "tableau" },
          h("thead", null, h("tr", null, h("th", null, "Produit"), h("th", { classe: "nombre" }, "Acceptés"), h("th", { classe: "nombre" }, "Proposés"))),
          h(
            "tbody",
            null,
            stats.produits_les_plus_acceptes.map((p) =>
              h("tr", null, h("td", null, p.libelle), h("td", { classe: "nombre" }, p.acceptes), h("td", { classe: "nombre" }, p.proposes)),
            ),
          ),
        ),
      ),
    ),
  ];
}

export const vueTableauDeBord: Vue = async (cible, parametres, contexte) => {
  const jours = Number(parametres["jours"] ?? 30);
  remplacer(cible, chargement("Calcul des indicateurs…"));
  try {
    const stats = await api.statistiques(jours);
    remplacer(
      cible,
      titrePage(
        contexte.peut("voir_statistiques_globales") ? "Tableau de bord" : "Mes résultats",
        contexte.peut("voir_statistiques_globales")
          ? "Efficacité des appels et des propositions du copilote"
          : `Vos appels et l'efficacité de vos propositions, ${contexte.session.utilisateur.nom_affiche}`,
        h(
          "div",
          { classe: "onglets", attrs: { style: "margin:0" } },
          PERIODES.map((p) =>
            h("button", { classe: p === jours ? "actif" : "", attrs: { type: "button" }, on: { click: () => contexte.naviguer(`/tableau-de-bord?jours=${p}`) } }, `${p} jours`),
          ),
        ),
      ),
      contenu(stats),
    );
  } catch (erreur) {
    remplacer(cible, messageErreur(erreur));
  }
};
