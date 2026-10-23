// Construction du DOM sans innerHTML : tout le texte est inséré via des nœuds texte,
// ce qui protège naturellement contre l'injection de HTML (XSS).
function ajouterEnfants(parent, enfants) {
    for (const enfant of enfants) {
        if (enfant === null || enfant === undefined || enfant === false)
            continue;
        if (Array.isArray(enfant))
            ajouterEnfants(parent, enfant);
        else if (enfant instanceof Node)
            parent.appendChild(enfant);
        else
            parent.appendChild(document.createTextNode(String(enfant)));
    }
}
function appliquerAttributs(element, attrs) {
    for (const [nom, valeur] of Object.entries(attrs ?? {})) {
        if (valeur === undefined || valeur === false)
            continue;
        element.setAttribute(nom, valeur === true ? "" : String(valeur));
    }
}
/** Crée un élément HTML : h("a", { classe: "bouton", attrs: { href: "#/" } }, "Accueil"). */
export function h(balise, proprietes = null, ...enfants) {
    const element = document.createElement(balise);
    if (proprietes?.classe)
        element.className = proprietes.classe;
    appliquerAttributs(element, proprietes?.attrs);
    for (const [evenement, gestionnaire] of Object.entries(proprietes?.on ?? {})) {
        element.addEventListener(evenement, gestionnaire);
    }
    ajouterEnfants(element, enfants);
    return element;
}
const NS_SVG = "http://www.w3.org/2000/svg";
/** Crée un élément SVG (graphiques). */
export function s(balise, attrs = {}, ...enfants) {
    const element = document.createElementNS(NS_SVG, balise);
    for (const [nom, valeur] of Object.entries(attrs))
        element.setAttribute(nom, String(valeur));
    ajouterEnfants(element, enfants);
    return element;
}
/** Remplace tout le contenu d'un conteneur. */
export function remplacer(conteneur, ...enfants) {
    conteneur.replaceChildren();
    ajouterEnfants(conteneur, enfants);
}
