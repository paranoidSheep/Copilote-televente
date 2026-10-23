// Préférences du poste (télévendeur sélectionné). Stockées dans le navigateur,
// avec repli silencieux si le stockage local est indisponible (navigation privée…).
const CLE_TELEVENDEUR = "copilote.televendeur";
function lire(cle) {
    try {
        return window.localStorage.getItem(cle);
    }
    catch {
        return null;
    }
}
function ecrire(cle, valeur) {
    try {
        if (valeur === null)
            window.localStorage.removeItem(cle);
        else
            window.localStorage.setItem(cle, valeur);
    }
    catch {
        // stockage indisponible : la préférence ne sera simplement pas mémorisée
    }
}
let televendeur = lire(CLE_TELEVENDEUR);
export const preferences = {
    get televendeur() {
        return televendeur;
    },
    set televendeur(valeur) {
        televendeur = valeur;
        ecrire(CLE_TELEVENDEUR, valeur);
    },
};
