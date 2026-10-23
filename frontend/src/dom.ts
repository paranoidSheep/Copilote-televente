// Construction du DOM sans innerHTML : tout le texte est inséré via des nœuds texte,
// ce qui protège naturellement contre l'injection de HTML (XSS).

export type Enfant = Node | string | number | null | undefined | false | readonly Enfant[];

type Gestionnaires = { [E in keyof HTMLElementEventMap]?: (evenement: HTMLElementEventMap[E]) => void };

export interface Proprietes {
  classe?: string;
  attrs?: Record<string, string | number | boolean | undefined>;
  on?: Gestionnaires;
}

function ajouterEnfants(parent: Node, enfants: readonly Enfant[]): void {
  for (const enfant of enfants) {
    if (enfant === null || enfant === undefined || enfant === false) continue;
    if (Array.isArray(enfant)) ajouterEnfants(parent, enfant);
    else if (enfant instanceof Node) parent.appendChild(enfant);
    else parent.appendChild(document.createTextNode(String(enfant)));
  }
}

function appliquerAttributs(element: Element, attrs: Proprietes["attrs"]): void {
  for (const [nom, valeur] of Object.entries(attrs ?? {})) {
    if (valeur === undefined || valeur === false) continue;
    element.setAttribute(nom, valeur === true ? "" : String(valeur));
  }
}

/** Crée un élément HTML : h("a", { classe: "bouton", attrs: { href: "#/" } }, "Accueil"). */
export function h<K extends keyof HTMLElementTagNameMap>(
  balise: K,
  proprietes: Proprietes | null = null,
  ...enfants: Enfant[]
): HTMLElementTagNameMap[K] {
  const element = document.createElement(balise);
  if (proprietes?.classe) element.className = proprietes.classe;
  appliquerAttributs(element, proprietes?.attrs);
  for (const [evenement, gestionnaire] of Object.entries(proprietes?.on ?? {})) {
    element.addEventListener(evenement, gestionnaire as EventListener);
  }
  ajouterEnfants(element, enfants);
  return element;
}

const NS_SVG = "http://www.w3.org/2000/svg";

/** Crée un élément SVG (graphiques). */
export function s<K extends keyof SVGElementTagNameMap>(
  balise: K,
  attrs: Record<string, string | number> = {},
  ...enfants: Enfant[]
): SVGElementTagNameMap[K] {
  const element = document.createElementNS(NS_SVG, balise);
  for (const [nom, valeur] of Object.entries(attrs)) element.setAttribute(nom, String(valeur));
  ajouterEnfants(element, enfants);
  return element;
}

/** Remplace tout le contenu d'un conteneur. */
export function remplacer(conteneur: Element, ...enfants: Enfant[]): void {
  conteneur.replaceChildren();
  ajouterEnfants(conteneur, enfants);
}
