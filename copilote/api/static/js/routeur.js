// Routage par fragment d'URL (#/…) : aucune configuration serveur nécessaire.
export class Routeur {
    routes = [];
    ajouter(chemin, rubrique, vue) {
        const noms = [];
        const motif = new RegExp("^" +
            chemin.replace(/:([a-z_]+)/g, (_tout, nom) => {
                noms.push(nom);
                return "([^/]+)";
            }) +
            "$");
        this.routes.push({ motif, noms, rubrique, vue });
        return this;
    }
    resoudre(fragment) {
        const [chemin = "/", requete = ""] = fragment.replace(/^#/, "").split("?");
        const parametres = Object.fromEntries(new URLSearchParams(requete));
        for (const route of this.routes) {
            const correspondance = route.motif.exec(chemin || "/");
            if (correspondance) {
                route.noms.forEach((nom, i) => (parametres[nom] = decodeURIComponent(correspondance[i + 1] ?? "")));
                return { route, parametres };
            }
        }
        return null;
    }
}
