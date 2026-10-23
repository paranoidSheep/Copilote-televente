// Formatage à la française et libellés des valeurs énumérées de l'API.
const formatEuros = new Intl.NumberFormat("fr-FR", { style: "currency", currency: "EUR" });
const formatNombre = new Intl.NumberFormat("fr-FR", { maximumFractionDigits: 1 });
export const euros = (montant) => montant === null || montant === undefined ? "—" : formatEuros.format(montant);
export const nombre = (valeur) => valeur === null || valeur === undefined ? "—" : formatNombre.format(valeur);
export const pourcentage = (valeur, signe = false) => valeur === null || valeur === undefined ? "—" : `${signe && valeur > 0 ? "+" : ""}${valeur} %`;
function versDate(iso) {
    return new Date(iso.length === 10 ? `${iso}T00:00:00` : iso);
}
export const dateCourte = (iso) => iso ? versDate(iso).toLocaleDateString("fr-FR", { day: "2-digit", month: "2-digit" }) : "—";
export const dateLongue = (iso) => iso ? versDate(iso).toLocaleDateString("fr-FR", { weekday: "long", day: "numeric", month: "long" }) : "—";
export const heure = (iso) => versDate(iso).toLocaleTimeString("fr-FR", { hour: "2-digit", minute: "2-digit" });
/** « 2 cartons », « 3 plateaux », « 6 kg » */
export function quantite(valeur, unite) {
    const pluriel = valeur >= 2 && !["kg", "L"].includes(unite) && !/[sx]$/.test(unite);
    return `${nombre(valeur)} ${pluriel ? unite + (/eau$/.test(unite) ? "x" : "s") : unite}`;
}
export function initiales(nom) {
    return nom
        .replace(/^(Le|La|Les|L'|Au|Aux|Chez)\s*/i, "")
        .split(/\s+/)
        .slice(0, 2)
        .map((mot) => mot.charAt(0))
        .join("")
        .toUpperCase();
}
export const LIBELLES = {
    issue: {
        commande: "Commande",
        pas_de_besoin: "Pas de besoin",
        rappeler: "À rappeler",
        injoignable: "Injoignable",
    },
    origine: {
        manquant: "Habituel",
        stock: "À écouler",
        suggestion: "Suggestion",
        autre: "Autre",
    },
    reponse: {
        accepte: "Accepté",
        refuse: "Refusé",
        sans_reponse: "Sans réponse",
    },
    statut: { en_retard: "en retard", decroche: "décroché" },
    motif: { dlc_courte: "DLC courte", surstock: "Surstock" },
    niveau: { haute: "Priorité haute", moyenne: "Priorité moyenne", basse: "Priorité basse" },
    modeFiche: {
        ia: "Rédigée par IA",
        ia_simulee: "IA simulée",
        repli: "Sans IA (repli)",
    },
    modeLLM: {
        auto: "Automatique",
        anthropic: "Claude",
        openai: "OpenAI",
        mistral: "Mistral AI",
        gemini: "Gemini",
        compatible: "Compatible OpenAI",
        simule: "IA simulée",
        repli: "Sans IA",
    },
    pertinence: {
        0: "Aucune",
        1: "Clients similaires",
        2: "Déjà acheté",
        3: "Habituel",
    },
    etape: { appel_llm: "🧠", outil: "🔧", garde_fou: "🛡️" },
    correction: {
        produit_inconnu: "Produit inventé écarté",
        offre_refusee: "Offre refusée récemment retirée",
        remise_plafonnee: "Remise ramenée au maximum",
        selection_limitee: "Sélection trop longue",
        stock_complete: "Stock complété par les analyses",
        accroche_retiree: "Accroche vantant une offre retirée",
        accroches_limitees: "Accroches trop nombreuses",
        accroches_completees: "Accroches complétées",
        rappel_ajoute: "Rappel promis oublié",
    },
};
/** Nom d'un fournisseur tel qu'il figure dans une trace (« compatible ») → son libellé (« Ollama »). */
export function libelleFournisseur(nom, libelleMode) {
    const estMode = (valeur) => valeur in LIBELLES.modeLLM;
    return estMode(nom) ? libelleMode(nom) : nom;
}
export const jours = (liste) => (liste.length ? liste.join(", ") : "sans jour fixe");
