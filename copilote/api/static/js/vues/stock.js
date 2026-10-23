// Plan d'écoulement : pour chaque produit à écouler, les clients à appeler en priorité.
import { api } from "../api.js";
import { badge, carte, chargement, kpi, messageErreur, titrePage, vide } from "../composants.js";
import { h, remplacer } from "../dom.js";
import { dateCourte, euros, LIBELLES, quantite } from "../format.js";
function ligneEcoulement(ligne) {
    const s = ligne.situation;
    return carte(null, [
        h("div", { classe: "entree" }, h("span", { classe: "nom" }, s.libelle), h("span", { classe: "prix" }, h("span", { classe: "barre" }, euros(s.prix_unitaire_ht)), " ", h("strong", null, euros(s.prix_remise_ht)), h("br"), h("span", { classe: "remise" }, `−${s.remise_suggeree_pct} %`))),
        h("div", { classe: "meta" }, s.motifs.map((m) => [badge(LIBELLES.motif[m], m === "dlc_courte" ? "alerte" : "attention"), " "]), `Lot ${s.lot_id} · ${quantite(s.quantite_lot, s.unite)} · DLC ${dateCourte(s.dlc)} (J+${s.jours_avant_dlc})`, s.couverture_jours !== null ? ` · ${Math.round(s.couverture_jours)} j de stock` : " · aucune vente récente", ` · valeur ${euros(ligne.valeur_lot_ht)}`),
        h("div", { classe: "ligne petit", attrs: { style: "margin:10px 0 6px" } }, h("span", null, `Clients ciblés : potentiel ${quantite(ligne.quantite_potentielle, s.unite)}`), h("span", { classe: "espace" }), h("span", { classe: "gras" }, `${ligne.couverture_plan_pct} % du lot`)),
        h("div", { classe: "jauge" }, h("span", { attrs: { style: `width:${ligne.couverture_plan_pct}%` } })),
        ligne.clients.length
            ? h("ul", { classe: "liste", attrs: { style: "margin-top:10px" } }, ligne.clients.map((c) => h("li", null, h("div", { classe: "entree" }, h("a", { classe: "nom", attrs: { href: `#/clients/${encodeURIComponent(c.client_id)}` } }, c.nom), badge(LIBELLES.pertinence[c.pertinence], c.pertinence === 3 ? "succes" : c.pertinence === 2 ? "primaire" : "info")), h("div", { classe: "meta" }, `${c.type} · ${c.commercial} · ${c.raison} · ~${quantite(c.quantite_estimee, s.unite)}`))))
            : vide("Aucun client identifié pour ce produit."),
    ]);
}
export const vueStock = async (cible) => {
    remplacer(cible, chargement("Calcul du plan d'écoulement…"));
    try {
        const plan = await api.planEcoulement();
        let filtre = "dlc_courte";
        const liste = h("div", { classe: "pile" });
        const rafraichir = () => {
            const lignes = plan.lignes.filter((l) => filtre === "tous" || l.situation.motifs.includes(filtre));
            remplacer(liste, lignes.length ? lignes.map(ligneEcoulement) : carte(null, vide("Aucun produit dans cette catégorie.")));
        };
        const choix = [
            ["dlc_courte", "DLC courte"],
            ["surstock", "Surstock"],
            ["tous", "Tous"],
        ];
        const onglets = h("div", { classe: "onglets" }, choix.map(([valeur, libelle]) => h("button", {
            classe: valeur === filtre ? "actif" : "",
            attrs: { type: "button" },
            on: {
                click: (e) => {
                    filtre = valeur;
                    for (const b of onglets.children)
                        b.classList.toggle("actif", b === e.currentTarget);
                    rafraichir();
                },
            },
        }, libelle)));
        remplacer(cible, titrePage("Stock à écouler", "Lots à DLC courte et surstocks, avec les clients à qui les proposer"), h("div", { classe: "kpis", attrs: { style: "margin-bottom:12px" } }, kpi(euros(plan.valeur_a_risque_ht), "Valeur à DLC courte", "baisse"), kpi(plan.nb_lots_urgents, "Lots urgents"), kpi(plan.lignes.length, "Produits à écouler"), kpi(`${Math.round(plan.lignes.reduce((t, l) => t + l.couverture_plan_pct, 0) / Math.max(1, plan.lignes.length))} %`, "Couverture moyenne du plan")), onglets, liste);
        rafraichir();
    }
    catch (erreur) {
        remplacer(cible, messageErreur(erreur));
    }
};
