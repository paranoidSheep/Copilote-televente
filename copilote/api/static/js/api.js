// Client HTTP typé de l'API du copilote. Les types viennent de `types-api.ts`,
// généré à partir du schéma OpenAPI du backend : front et back restent alignés.
/** Émis quand le serveur répond 401 : la session a expiré ou a été fermée. */
export const EVENEMENT_SESSION_EXPIREE = "copilote:session-expiree";
export class ErreurApi extends Error {
    statut;
    constructor(statut, message) {
        super(message);
        this.statut = statut;
        this.name = "ErreurApi";
    }
}
function url(chemin, parametres = {}) {
    const recherche = new URLSearchParams();
    for (const [cle, valeur] of Object.entries(parametres)) {
        if (valeur !== null && valeur !== undefined && valeur !== "")
            recherche.set(cle, String(valeur));
    }
    const requete = recherche.toString();
    return requete ? `${chemin}?${requete}` : chemin;
}
function detailErreur(corps, statut) {
    if (typeof corps === "object" && corps !== null && "detail" in corps) {
        const detail = corps.detail;
        if (typeof detail === "string")
            return detail;
        if (Array.isArray(detail)) {
            return detail
                .map((e) => (typeof e === "object" && e !== null && "msg" in e ? String(e.msg) : ""))
                .filter(Boolean)
                .join(" ; ");
        }
    }
    return `Erreur ${statut}`;
}
async function requete(chemin, init) {
    const reponse = await fetch(chemin, { headers: { Accept: "application/json" }, ...init });
    const type = reponse.headers.get("content-type") ?? "";
    const corps = type.includes("application/json") ? await reponse.json() : await reponse.text();
    if (reponse.status === 401 && !chemin.startsWith("/auth/") && chemin !== "/session") {
        window.dispatchEvent(new CustomEvent(EVENEMENT_SESSION_EXPIREE));
    }
    if (!reponse.ok)
        throw new ErreurApi(reponse.status, detailErreur(corps, reponse.status));
    // Le contrat est garanti par le schéma OpenAPI dont sont générés les types.
    return corps;
}
const id = encodeURIComponent;
const json = (methode, corps) => ({
    method: methode,
    headers: { "Content-Type": "application/json", Accept: "application/json" },
    ...(corps === undefined ? {} : { body: JSON.stringify(corps) }),
});
export const api = {
    session: () => requete("/session"),
    connexion: (identifiant, motDePasse) => requete("/auth/connexion", json("POST", { identifiant, mot_de_passe: motDePasse })),
    deconnexion: () => requete("/auth/deconnexion", json("POST")),
    clients: (filtres = {}) => requete(url("/clients", filtres)),
    client360: (clientId) => requete(`/clients/${id(clientId)}`),
    fiche: (clientId, mode, regenerer = false) => requete(url(`/clients/${id(clientId)}/fiche`, { mode, regenerer: regenerer || undefined })),
    produit: (clientId, code) => requete(`/clients/${id(clientId)}/produits/${id(code)}`),
    fileAppels: (televendeur) => requete(url("/appels/file", { televendeur })),
    enregistrerCompteRendu: (saisie) => requete("/comptes-rendus", json("POST", saisie)),
    comptesRendus: (filtres = {}) => requete(url("/comptes-rendus", filtres)),
    statistiques: (jours) => requete(url("/statistiques", { jours })),
    planEcoulement: () => requete("/stock/plan-ecoulement"),
    diagnostic: () => requete("/admin/diagnostic"),
    labo: {
        agent: (clientId) => requete(url("/labo/agent", { client_id: clientId })),
        outils: (clientId, produit) => requete(url(`/labo/clients/${id(clientId)}/outils`, { produit })),
        comparaison: (clientId) => requete(`/labo/clients/${id(clientId)}/comparaison`),
        evaluations: () => requete("/labo/evaluations"),
        evaluation: (campagneId) => requete(`/labo/evaluations/${campagneId}`),
        suiviEvaluation: () => requete("/labo/evaluations/suivi"),
        lancerEvaluation: (demande) => requete("/labo/evaluations", json("POST", demande)),
        rapportEvaluation: (campagneId) => `/labo/evaluations/${campagneId}/rapport.md`,
    },
};
