// Page de connexion : identifiant et mot de passe, session ouverte par un cookie sécurisé.
import { api, ErreurApi } from "../api.js";
import { h, remplacer } from "../dom.js";
export function afficherConnexion(racine, apresConnexion) {
    const identifiant = h("input", {
        classe: "champ",
        attrs: { name: "identifiant", autocomplete: "username", required: true, autocapitalize: "none", spellcheck: "false" },
    });
    const motDePasse = h("input", {
        classe: "champ",
        attrs: { name: "mot_de_passe", type: "password", autocomplete: "current-password", required: true },
    });
    const message = h("div", { attrs: { role: "alert", "aria-live": "polite" } });
    const bouton = h("button", { classe: "bouton principal", attrs: { type: "submit" } }, "Se connecter");
    const formulaire = h("form", {
        classe: "formulaire",
        on: {
            submit: async (evenement) => {
                evenement.preventDefault();
                bouton.disabled = true;
                remplacer(message);
                try {
                    await api.connexion(identifiant.value.trim(), motDePasse.value);
                    apresConnexion();
                }
                catch (erreur) {
                    const texte = erreur instanceof ErreurApi && erreur.statut === 429
                        ? erreur.message
                        : erreur instanceof ErreurApi && erreur.statut === 401
                            ? "Identifiant ou mot de passe incorrect."
                            : "Connexion impossible pour le moment.";
                    remplacer(message, h("p", { classe: "message-erreur" }, texte));
                    motDePasse.value = "";
                    motDePasse.focus();
                }
                finally {
                    bouton.disabled = false;
                }
            },
        },
    }, h("label", { classe: "etiquette" }, "Identifiant", identifiant), h("label", { classe: "etiquette" }, "Mot de passe", motDePasse), message, bouton);
    remplacer(racine, h("main", { classe: "page-connexion" }, h("section", { classe: "carte connexion" }, h("div", { classe: "logo", attrs: { "aria-hidden": "true" } }, "📞"), h("h1", null, "Copilote télévente"), h("p", { classe: "doux" }, "Connectez-vous pour préparer vos appels."), formulaire), h("p", { classe: "pied" }, "Accès réservé aux équipes de télévente. Vos identifiants vous sont remis par votre responsable.")));
    identifiant.focus();
}
