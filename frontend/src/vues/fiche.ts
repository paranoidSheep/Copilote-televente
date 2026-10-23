// Fiche d'appel d'un client : à lire juste avant de décrocher, puis à compléter après l'appel.

import { api } from "../api.js";
import {
  badge,
  boutonCopier,
  carte,
  chargement,
  kpi,
  messageErreur,
  repliable,
  traceExecution,
  variationClasse,
} from "../composants.js";
import { h, remplacer } from "../dom.js";
import { dateCourte, euros, heure, jours, LIBELLES, nombre, pourcentage, quantite } from "../format.js";
import type { Contexte, Vue } from "../routeur.js";
import type { Fiche, ModeLLM } from "../types-api.js";
import { formulaireCompteRendu } from "./compte-rendu.js";

function entete(fiche: Fiche, contexte: Contexte, recharger: (mode: ModeLLM | undefined, regenerer: boolean) => void, modeCourant: ModeLLM | undefined) {
  const c = fiche.client;
  const h_ = fiche.habitudes;
  const choixMode = h(
    "select",
    {
      classe: "champ",
      attrs: { "aria-label": "Rédacteur de la fiche", style: "width:auto" },
      on: { change: (e) => recharger(((e.target as HTMLSelectElement).value || undefined) as ModeLLM | undefined, false) },
    },
    h("option", { attrs: { value: "" } }, `Rédacteur par défaut (${LIBELLES.modeLLM[contexte.sante.mode_par_defaut]})`),
    contexte.sante.modes_disponibles.map((m) =>
      h("option", { attrs: { value: m.mode, selected: m.mode === modeCourant } }, m.libelle),
    ),
  );
  return h(
    "section",
    { classe: "carte" },
    h("div", { classe: "ligne" }, h("h2", { attrs: { style: "font-size:1.35rem" } }, c.nom), h("span", { classe: "espace" }),
      h("a", { classe: "bouton discret", attrs: { href: `#/clients/${encodeURIComponent(c.id)}/360` } }, "Vue 360 ›")),
    h(
      "p",
      { classe: "doux", attrs: { style: "margin:2px 0 12px" } },
      `${c.type} · ${c.ville} · ${c.contact}`,
      h_.prochain_jour_habituel ? h("span", null, " · prochaine commande habituelle ", h("strong", null, dateCourte(h_.prochain_jour_habituel))) : null,
    ),
    h(
      "div",
      { classe: "ligne" },
      h("a", { classe: "bouton principal", attrs: { href: `tel:${c.telephone.replace(/\s/g, "")}` } }, `📞 ${c.telephone}`),
      boutonCopier(() => fiche.texte, "Copier la fiche"),
      h("button", { classe: "bouton", attrs: { type: "button" }, on: { click: () => recharger(modeCourant, true) } }, "Régénérer"),
      choixMode,
    ),
    h(
      "p",
      { classe: "petit doux", attrs: { style: "margin:10px 0 0" } },
      badge(LIBELLES.modeFiche[fiche.mode], fiche.mode === "repli" ? "attention" : "info"),
      " ",
      fiche.modele ?? "",
      fiche.avertissement ? h("span", null, " — ", fiche.avertissement) : null,
      ` · générée à ${heure(fiche.genere_le)}`,
    ),
  );
}

function habitudes(fiche: Fiche) {
  const h_ = fiche.habitudes;
  return carte(
    "Habitudes du client",
    [
      h("p", { attrs: { style: "margin:0 0 12px" } }, fiche.resume_habitudes),
      h(
        "div",
        { classe: "kpis" },
        kpi(euros(h_.panier_moyen_ht), "Panier moyen HT"),
        kpi(nombre(h_.commandes_par_semaine), "Commandes / semaine"),
        kpi(`${h_.jours_depuis_derniere_commande ?? "—"} j`, "Depuis la dernière commande"),
        kpi(pourcentage(h_.tendance_ca_pct, true), "Tendance 3 mois", variationClasse(h_.tendance_ca_pct)),
      ),
      h("p", { classe: "meta" }, `Jours de commande : ${jours(h_.jours_habituels)}`),
      h(
        "div",
        { classe: "puces" },
        h_.produits_recurrents.slice(0, 8).map((p) => h("span", { classe: "puce" }, `${p.libelle} · ${p.frequence_pct} %`)),
      ),
    ],
  );
}

function manquants(fiche: Fiche) {
  return carte(
    "Habituels pas encore commandés",
    fiche.produits_manquants.length
      ? h(
          "ul",
          { classe: "liste" },
          fiche.produits_manquants.map((m) =>
            h(
              "li",
              null,
              h("div", { classe: "entree" }, h("span", { classe: "nom" }, m.libelle), m.statut === "decroche" ? badge("décroché", "alerte") : badge("en retard", "attention")),
              h(
                "div",
                { classe: "meta" },
                `Habituellement ${quantite(m.quantite_habituelle, m.unite)} tous les ${nombre(m.rythme_habituel_jours)} j · dernière commande le ${dateCourte(m.derniere_commande)} (il y a ${m.jours_depuis_derniere_commande} j)`,
              ),
              h("div", { classe: "argument" }, m.commentaire),
            ),
          ),
        )
      : h("p", { classe: "vide" }, "Rien à signaler : le client est à jour de ses commandes habituelles."),
    { compte: fiche.produits_manquants.length },
  );
}

function stock(fiche: Fiche) {
  return carte(
    "Stock à écouler",
    fiche.stock_a_ecouler.length
      ? h(
          "ul",
          { classe: "liste" },
          fiche.stock_a_ecouler.map((s) =>
            h(
              "li",
              null,
              h(
                "div",
                { classe: "entree" },
                h("span", { classe: "nom" }, s.libelle),
                h(
                  "span",
                  { classe: "prix" },
                  s.remise_pct ? h("span", { classe: "barre" }, euros(s.prix_unitaire_ht), " ") : null,
                  h("strong", null, euros(s.prix_propose_ht)),
                  s.remise_pct ? [h("br"), h("span", { classe: "remise" }, `−${s.remise_pct} %`)] : null,
                ),
              ),
              h(
                "div",
                { classe: "meta" },
                s.motifs.map((m) => [badge(LIBELLES.motif[m], m === "dlc_courte" ? "alerte" : "attention"), " "]),
                `DLC ${dateCourte(s.dlc)} (J+${s.jours_avant_dlc}) · lot ${s.lot_id} · ${quantite(s.quantite_lot, s.unite)} dispo · ${LIBELLES.pertinence[s.pertinence].toLowerCase()}`,
              ),
              h("div", { classe: "argument" }, s.argument),
            ),
          ),
        )
      : h("p", { classe: "vide" }, "Aucun produit à écouler pertinent pour ce client."),
    { compte: fiche.stock_a_ecouler.length },
  );
}

function suggestions(fiche: Fiche) {
  if (!fiche.suggestions.length) return null;
  return carte(
    "À proposer aussi",
    h(
      "ul",
      { classe: "liste" },
      fiche.suggestions.map((s) =>
        h(
          "li",
          null,
          h("div", { classe: "entree" }, h("span", { classe: "nom" }, s.libelle), h("span", { classe: "prix" }, euros(s.prix_unitaire_ht))),
          h("div", { classe: "meta" }, `Adopté par ${s.taux_adoption_pct} % des établissements similaires`),
          h("div", { classe: "argument" }, s.argument),
        ),
      ),
    ),
    { compte: fiche.suggestions.length },
  );
}

function appelsPrecedents(fiche: Fiche) {
  const appels = fiche.appels_precedents.appels;
  if (!appels.length) return null;
  return repliable(
    `Appels précédents (${appels.length})`,
    h(
      "ul",
      { classe: "liste" },
      appels.map((a) =>
        h(
          "li",
          null,
          h("div", { classe: "entree" }, h("span", { classe: "nom" }, `${dateCourte(a.jour)} · ${a.televendeur}`), badge(LIBELLES.issue[a.issue])),
          a.notes ? h("div", { classe: "argument" }, a.notes) : null,
          a.produits_acceptes.length ? h("div", { classe: "meta" }, `Acceptés : ${a.produits_acceptes.join(", ")}`) : null,
          a.produits_refuses.length ? h("div", { classe: "meta" }, `Refusés : ${a.produits_refuses.join(", ")}`) : null,
        ),
      ),
    ),
  );
}

export const vueFiche: Vue = async (cible, parametres, contexte) => {
  const clientId = parametres["id"] ?? "";

  const afficher = async (mode: ModeLLM | undefined, regenerer: boolean): Promise<void> => {
    remplacer(cible, chargement("Préparation de la fiche d'appel…", "L'IA analyse l'historique, le stock et les appels précédents."));
    let fiche: Fiche;
    try {
      fiche = await api.fiche(clientId, mode, regenerer);
    } catch (erreur) {
      remplacer(cible, messageErreur(erreur));
      return;
    }
    document.title = `${fiche.client.nom} — Fiche d'appel`;
    remplacer(
      cible,
      h(
        "div",
        { classe: "grille fiche" },
        h(
          "div",
          { classe: "pile" },
          entete(fiche, contexte, (m, r) => void afficher(m, r), mode),
          fiche.accroches.length
            ? carte("À dire au téléphone", h("ol", { classe: "accroches" }, fiche.accroches.map((a) => h("li", null, `« ${a} »`))), { classe: "accent" })
            : null,
          fiche.points_attention.length ? carte("Points d'attention", h("ul", null, fiche.points_attention.map((p) => h("li", null, p))), { classe: "alerte" }) : null,
          habitudes(fiche),
          manquants(fiche),
        ),
        h(
          "div",
          { classe: "pile" },
          stock(fiche),
          suggestions(fiche),
          formulaireCompteRendu(fiche, () => undefined),
          appelsPrecedents(fiche),
          fiche.garde_fous.length
            ? repliable(`Corrections automatiques (${fiche.garde_fous.length})`, h("ul", null, fiche.garde_fous.map((g) => h("li", { classe: "petit" }, g))))
            : null,
          fiche.trace ? repliable("Coulisses de l'IA", traceExecution(fiche.trace)) : null,
          repliable("Version texte", h("pre", { classe: "code" }, fiche.texte)),
        ),
      ),
    );
  };

  await afficher(undefined, false);
};
