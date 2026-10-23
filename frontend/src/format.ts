// Formatage à la française et libellés des valeurs énumérées de l'API.

import type {
  Issue,
  JourSemaine,
  ModeFiche,
  ModeLLM,
  MotifEcoulement,
  NiveauPriorite,
  Origine,
  Pertinence,
  Reponse,
  StatutManquant,
  TypeCorrection,
  TypeEtape,
} from "./types-api.js";

const formatEuros = new Intl.NumberFormat("fr-FR", { style: "currency", currency: "EUR" });
const formatNombre = new Intl.NumberFormat("fr-FR", { maximumFractionDigits: 1 });

export const euros = (montant: number | null | undefined): string =>
  montant === null || montant === undefined ? "—" : formatEuros.format(montant);

export const nombre = (valeur: number | null | undefined): string =>
  valeur === null || valeur === undefined ? "—" : formatNombre.format(valeur);

export const pourcentage = (valeur: number | null | undefined, signe = false): string =>
  valeur === null || valeur === undefined ? "—" : `${signe && valeur > 0 ? "+" : ""}${valeur} %`;

function versDate(iso: string): Date {
  return new Date(iso.length === 10 ? `${iso}T00:00:00` : iso);
}

export const dateCourte = (iso: string | null | undefined): string =>
  iso ? versDate(iso).toLocaleDateString("fr-FR", { day: "2-digit", month: "2-digit" }) : "—";

export const dateLongue = (iso: string | null | undefined): string =>
  iso ? versDate(iso).toLocaleDateString("fr-FR", { weekday: "long", day: "numeric", month: "long" }) : "—";

export const heure = (iso: string): string =>
  versDate(iso).toLocaleTimeString("fr-FR", { hour: "2-digit", minute: "2-digit" });

/** « 2 cartons », « 3 plateaux », « 6 kg » */
export function quantite(valeur: number, unite: string): string {
  const pluriel = valeur >= 2 && !["kg", "L"].includes(unite) && !/[sx]$/.test(unite);
  return `${nombre(valeur)} ${pluriel ? unite + (/eau$/.test(unite) ? "x" : "s") : unite}`;
}

export function initiales(nom: string): string {
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
  } satisfies Record<Issue, string>,
  origine: {
    manquant: "Habituel",
    stock: "À écouler",
    suggestion: "Suggestion",
    autre: "Autre",
  } satisfies Record<Origine, string>,
  reponse: {
    accepte: "Accepté",
    refuse: "Refusé",
    sans_reponse: "Sans réponse",
  } satisfies Record<Reponse, string>,
  statut: { en_retard: "en retard", decroche: "décroché" } satisfies Record<StatutManquant, string>,
  motif: { dlc_courte: "DLC courte", surstock: "Surstock" } satisfies Record<MotifEcoulement, string>,
  niveau: { haute: "Priorité haute", moyenne: "Priorité moyenne", basse: "Priorité basse" } satisfies Record<
    NiveauPriorite,
    string
  >,
  modeFiche: {
    ia: "Rédigée par IA",
    ia_simulee: "IA simulée",
    repli: "Sans IA (repli)",
  } satisfies Record<ModeFiche, string>,
  modeLLM: {
    auto: "Automatique",
    anthropic: "Claude",
    openai: "OpenAI",
    mistral: "Mistral AI",
    gemini: "Gemini",
    compatible: "Compatible OpenAI",
    simule: "IA simulée",
    repli: "Sans IA",
  } satisfies Record<ModeLLM, string>,
  pertinence: {
    0: "Aucune",
    1: "Clients similaires",
    2: "Déjà acheté",
    3: "Habituel",
  } satisfies Record<Pertinence, string>,
  etape: { appel_llm: "🧠", outil: "🔧", garde_fou: "🛡️" } satisfies Record<TypeEtape, string>,
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
  } satisfies Record<TypeCorrection, string>,
} as const;

/** Nom d'un fournisseur tel qu'il figure dans une trace (« compatible ») → son libellé (« Ollama »). */
export function libelleFournisseur(nom: string, libelleMode: (mode: ModeLLM) => string): string {
  const estMode = (valeur: string): valeur is ModeLLM => valeur in LIBELLES.modeLLM;
  return estMode(nom) ? libelleMode(nom) : nom;
}

export const jours = (liste: readonly JourSemaine[]): string => (liste.length ? liste.join(", ") : "sans jour fixe");
