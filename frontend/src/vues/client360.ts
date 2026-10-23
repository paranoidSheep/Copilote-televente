// Vue 360 d'un client : chiffres, évolution, produits et historique des appels.

import { api } from "../api.js";
import { badge, barresHorizontales, carte, chargement, histogramme, kpi, messageErreur, titrePage, variationClasse, vide } from "../composants.js";
import { h, remplacer } from "../dom.js";
import { dateCourte, euros, jours, LIBELLES, nombre, pourcentage, quantite } from "../format.js";
import type { Vue } from "../routeur.js";

const MOIS = ["janv.", "févr.", "mars", "avr.", "mai", "juin", "juil.", "août", "sept.", "oct.", "nov.", "déc."];

export const vueClient360: Vue = async (cible, parametres) => {
  const clientId = parametres["id"] ?? "";
  remplacer(cible, chargement("Chargement de la vue client…"));
  try {
    const vue = await api.client360(clientId);
    const { client: c, habitudes: hb, comptes_rendus: comptesRendus } = vue;
    document.title = `${c.nom} — Vue 360`;
    remplacer(
      cible,
      titrePage(
        c.nom,
        `${c.type} · ${c.ville} · ${c.contact} · ${c.telephone} · suivi par ${c.commercial}`,
        h("a", { classe: "bouton principal", attrs: { href: `#/clients/${encodeURIComponent(c.id)}` } }, "Fiche d'appel"),
      ),
      h(
        "div",
        { classe: "kpis", attrs: { style: "margin-bottom:12px" } },
        kpi(euros(hb.ca_total_ht), "CA sur 6 mois"),
        kpi(euros(hb.panier_moyen_ht), "Panier moyen HT"),
        kpi(`${nombre(hb.commandes_par_semaine)} / sem.`, `${hb.nb_commandes} commandes · ${jours(hb.jours_habituels)}`),
        kpi(pourcentage(hb.tendance_ca_pct, true), "Tendance 3 mois", variationClasse(hb.tendance_ca_pct)),
      ),
      h(
        "div",
        { classe: "grille deux" },
        carte(
          "Chiffre d'affaires mensuel",
          hb.ca_mensuel.length
            ? histogramme(
                hb.ca_mensuel.map((m) => ({
                  libelle: MOIS[Number(m.mois.slice(5, 7)) - 1] ?? m.mois,
                  valeur: m.ca_ht,
                  info: `${m.mois} : ${euros(m.ca_ht)}`,
                })),
              )
            : vide("Pas de commande sur la période."),
        ),
        carte(
          "Répartition des achats",
          barresHorizontales(
            hb.repartition_categories.slice(0, 7).map((p) => ({ libelle: p.categorie, valeur: p.part_pct, affichage: `${p.part_pct} %` })),
            100,
          ),
        ),
        carte(
          "Produits récurrents",
          h(
            "div",
            { classe: "tableau-conteneur" },
            h(
              "table",
              { classe: "tableau" },
              h("thead", null, h("tr", null, h("th", null, "Produit"), h("th", { classe: "nombre" }, "Fréquence"), h("th", { classe: "nombre" }, "Quantité"), h("th", { classe: "nombre" }, "Dernière"))),
              h(
                "tbody",
                null,
                hb.produits_recurrents.map((p) =>
                  h(
                    "tr",
                    null,
                    h("td", null, h("a", { attrs: { href: `#/labo?client=${encodeURIComponent(c.id)}&produit=${encodeURIComponent(p.code)}` } }, p.libelle)),
                    h("td", { classe: "nombre" }, `${p.frequence_pct} %`),
                    h("td", { classe: "nombre" }, quantite(p.quantite_habituelle, p.unite)),
                    h("td", { classe: "nombre" }, dateCourte(p.derniere_commande)),
                  ),
                ),
              ),
            ),
          ),
          { compte: hb.produits_recurrents.length },
        ),
        carte(
          "Historique des appels",
          comptesRendus.length
            ? h(
                "ul",
                { classe: "liste" },
                comptesRendus.map((cr) =>
                  h(
                    "li",
                    null,
                    h(
                      "div",
                      { classe: "entree" },
                      h("span", { classe: "nom" }, `${dateCourte(cr.cree_le)} · ${cr.televendeur}`),
                      badge(LIBELLES.issue[cr.issue], cr.issue === "commande" ? "succes" : cr.issue === "rappeler" ? "alerte" : "neutre"),
                    ),
                    cr.notes ? h("div", { classe: "argument" }, cr.notes) : null,
                    cr.lignes.length
                      ? h(
                          "div",
                          { classe: "meta" },
                          cr.lignes.map((l) => `${l.libelle} : ${LIBELLES.reponse[l.reponse].toLowerCase()}`).join(" · "),
                        )
                      : null,
                  ),
                ),
              )
            : vide("Aucun appel enregistré pour ce client."),
          { compte: comptesRendus.length },
        ),
      ),
    );
  } catch (erreur) {
    remplacer(cible, messageErreur(erreur));
  }
};
