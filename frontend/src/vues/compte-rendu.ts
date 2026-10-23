// Formulaire de compte-rendu d'appel : le panier proposé, ligne par ligne (accepté / refusé),
// l'issue de l'appel, les notes et un éventuel rappel. Rien n'est écrit dans l'ERP :
// le compte-rendu est enregistré dans le journal local et un texte de saisie est fourni.

import { api } from "../api.js";
import { badge, boutonCopier, carte, messageErreur } from "../composants.js";
import { h, remplacer } from "../dom.js";
import { euros, LIBELLES } from "../format.js";
import { preferences } from "../preferences.js";
import type { Fiche, Issue, LigneCompteRendu_Input, LignePanier, Reponse } from "../types-api.js";

interface EtatLigne {
  ligne: LignePanier;
  reponse: Reponse;
  quantite: number;
}

const REPONSES: readonly Reponse[] = ["accepte", "refuse", "sans_reponse"];
const ISSUES: readonly Issue[] = ["commande", "pas_de_besoin", "rappeler", "injoignable"];

function controleReponse(etat: EtatLigne, auChangement: () => void) {
  const groupe = h("div", { classe: "segment", attrs: { role: "group", "aria-label": `Réponse pour ${etat.ligne.libelle}` } });
  const boutons = REPONSES.map((reponse) =>
    h(
      "button",
      {
        classe: `${reponse} ${etat.reponse === reponse ? "actif" : ""}`.trim(),
        attrs: { type: "button", "aria-pressed": etat.reponse === reponse ? "true" : "false" },
        on: {
          click: () => {
            etat.reponse = reponse;
            for (const b of boutons) {
              const actif = b.classList.contains(reponse);
              b.classList.toggle("actif", actif);
              b.setAttribute("aria-pressed", actif ? "true" : "false");
            }
            auChangement();
          },
        },
      },
      { accepte: "✓", refuse: "✗", sans_reponse: "–" }[reponse],
    ),
  );
  for (const b of boutons) b.title = LIBELLES.reponse[REPONSES[boutons.indexOf(b)] ?? "sans_reponse"];
  groupe.append(...boutons);
  return groupe;
}

export function formulaireCompteRendu(fiche: Fiche, apresEnregistrement: () => void): HTMLElement {
  const etats: EtatLigne[] = fiche.panier.lignes.map((ligne) => ({ ligne, reponse: "sans_reponse", quantite: ligne.quantite }));
  let issueChoisieManuellement = false;

  const total = h("span", { classe: "total nombre" });
  const selectIssue = h(
    "select",
    { classe: "champ", attrs: { "aria-label": "Issue de l'appel" } },
    ISSUES.map((issue) => h("option", { attrs: { value: issue } }, LIBELLES.issue[issue])),
  );
  const champRappel = h("input", { classe: "champ", attrs: { type: "date", min: fiche.date_du_jour } });
  const blocRappel = h("label", { classe: "etiquette masque" }, "Rappeler le", champRappel);
  const notes = h("textarea", { classe: "champ", attrs: { placeholder: "Notes (facultatif)", maxlength: 1000 } });
  const vendeurs = h(
    "select",
    { classe: "champ", attrs: { "aria-label": "Télévendeur" } },
    h("option", { attrs: { value: "" } }, "— Télévendeur —"),
  );
  const zoneMessage = h("div");

  const mettreAJour = (): void => {
    const montant = etats
      .filter((e) => e.reponse === "accepte")
      .reduce((somme, e) => somme + e.quantite * e.ligne.prix_net_ht, 0);
    total.textContent = `Commande acceptée : ${euros(montant)} HT`;
    if (!issueChoisieManuellement) {
      selectIssue.value = etats.some((e) => e.reponse === "accepte") ? "commande" : selectIssue.value === "commande" ? "pas_de_besoin" : selectIssue.value;
    }
    blocRappel.classList.toggle("masque", selectIssue.value !== "rappeler");
  };

  selectIssue.addEventListener("change", () => {
    issueChoisieManuellement = true;
    mettreAJour();
  });

  void api.sante().then((sante) => {
    for (const nom of sante.televendeurs) vendeurs.append(h("option", { attrs: { value: nom } }, nom));
    vendeurs.value = preferences.televendeur ?? fiche.client.commercial;
  });

  const lignes = etats.map((etat) => {
    const champQuantite = h("input", {
      attrs: { type: "number", min: 0, step: 0.5, value: etat.quantite, "aria-label": `Quantité ${etat.ligne.libelle}` },
      on: {
        input: (evenement) => {
          etat.quantite = Number((evenement.target as HTMLInputElement).value) || 0;
          mettreAJour();
        },
      },
    });
    return h(
      "li",
      { classe: "ligne-cr" },
      h(
        "div",
        null,
        h("div", { classe: "gras" }, etat.ligne.libelle),
        h(
          "div",
          { classe: "meta" },
          badge(LIBELLES.origine[etat.ligne.origine], etat.ligne.origine === "stock" ? "attention" : etat.ligne.origine === "manquant" ? "primaire" : "info"),
          ` ${euros(etat.ligne.prix_net_ht)} / ${etat.ligne.unite}`,
          etat.ligne.remise_pct ? ` (−${etat.ligne.remise_pct} %)` : "",
        ),
      ),
      h("div", { classe: "controles" }, champQuantite, controleReponse(etat, mettreAJour)),
    );
  });

  const enregistrer = h("button", { classe: "bouton principal", attrs: { type: "submit" } }, "Enregistrer le compte-rendu");

  const formulaire = h(
    "form",
    {
      classe: "formulaire",
      on: {
        submit: async (evenement) => {
          evenement.preventDefault();
          if (!vendeurs.value) {
            remplacer(zoneMessage, messageErreur("Choisissez le télévendeur."));
            return;
          }
          const issue = selectIssue.value as Issue;
          const lignesCr: LigneCompteRendu_Input[] = etats
            .filter((e) => e.reponse !== "sans_reponse" || issue === "commande")
            .map((e) => ({
              code: e.ligne.code,
              libelle: e.ligne.libelle,
              unite: e.ligne.unite,
              origine: e.ligne.origine,
              reponse: e.reponse,
              quantite: e.reponse === "accepte" ? e.quantite : 0,
              prix_unitaire_ht: e.ligne.prix_unitaire_ht,
              remise_pct: e.ligne.remise_pct,
            }));
          enregistrer.disabled = true;
          try {
            const resultat = await api.enregistrerCompteRendu({
              client_id: fiche.client.id,
              televendeur: vendeurs.value,
              issue,
              notes: notes.value.trim(),
              rappel_le: issue === "rappeler" ? champRappel.value || null : null,
              mode_fiche: fiche.mode,
              lignes: lignesCr,
            });
            preferences.televendeur = vendeurs.value;
            remplacer(
              formulaire,
              h("p", { classe: "message-succes" }, `Compte-rendu enregistré (${LIBELLES.issue[resultat.compte_rendu.issue]}).`),
              resultat.compte_rendu.issue === "commande"
                ? h(
                    "div",
                    { classe: "pile" },
                    h("div", { classe: "gras" }, "À saisir dans l'ERP"),
                    h("pre", { classe: "code" }, resultat.texte_saisie_erp),
                    h("div", { classe: "ligne" }, boutonCopier(() => resultat.texte_saisie_erp, "Copier le bon")),
                  )
                : null,
              h("div", { classe: "ligne" }, h("a", { classe: "bouton", attrs: { href: "#/" } }, "Retour à la file d'appels")),
            );
            apresEnregistrement();
          } catch (erreur) {
            remplacer(zoneMessage, messageErreur(erreur));
            enregistrer.disabled = false;
          }
        },
      },
    },
    etats.length ? h("ul", { classe: "liste" }, lignes) : h("p", { classe: "vide" }, "Aucun produit proposé."),
    h("div", { classe: "ligne" }, total),
    h(
      "div",
      { classe: "colonnes" },
      h("label", { classe: "etiquette" }, "Issue de l'appel", selectIssue),
      h("label", { classe: "etiquette" }, "Télévendeur", vendeurs),
    ),
    blocRappel,
    notes,
    zoneMessage,
    h("div", { classe: "ligne" }, enregistrer),
  );
  mettreAJour();
  return carte("Compte-rendu d'appel", formulaire, { classe: "" });
}
