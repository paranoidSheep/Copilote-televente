// Client HTTP typé de l'API du copilote. Les types viennent de `types-api.ts`,
// généré à partir du schéma OpenAPI du backend : front et back restent alignés.

import type {
  Client,
  Client360,
  CompteRendu,
  CompteRenduEnregistre,
  ConfigurationAgent,
  DetailsProduit,
  Fiche,
  FileAppels,
  ContexteSession,
  ModeLLM,
  PlanEcoulement,
  RapportDiagnostic,
  ResultatOutilLabo,
  SaisieCompteRendu,
  StatistiquesAppels,
  Utilisateur,
} from "./types-api.js";

/** Émis quand le serveur répond 401 : la session a expiré ou a été fermée. */
export const EVENEMENT_SESSION_EXPIREE = "copilote:session-expiree";

export class ErreurApi extends Error {
  constructor(
    readonly statut: number,
    message: string,
  ) {
    super(message);
    this.name = "ErreurApi";
  }
}

type Parametres = Record<string, string | number | boolean | null | undefined>;

function url(chemin: string, parametres: Parametres = {}): string {
  const recherche = new URLSearchParams();
  for (const [cle, valeur] of Object.entries(parametres)) {
    if (valeur !== null && valeur !== undefined && valeur !== "") recherche.set(cle, String(valeur));
  }
  const requete = recherche.toString();
  return requete ? `${chemin}?${requete}` : chemin;
}

function detailErreur(corps: unknown, statut: number): string {
  if (typeof corps === "object" && corps !== null && "detail" in corps) {
    const detail = (corps as { detail: unknown }).detail;
    if (typeof detail === "string") return detail;
    if (Array.isArray(detail)) {
      return detail
        .map((e: unknown) => (typeof e === "object" && e !== null && "msg" in e ? String((e as { msg: unknown }).msg) : ""))
        .filter(Boolean)
        .join(" ; ");
    }
  }
  return `Erreur ${statut}`;
}

async function requete<T>(chemin: string, init?: RequestInit): Promise<T> {
  const reponse = await fetch(chemin, { headers: { Accept: "application/json" }, ...init });
  const type = reponse.headers.get("content-type") ?? "";
  const corps: unknown = type.includes("application/json") ? await reponse.json() : await reponse.text();
  if (reponse.status === 401 && !chemin.startsWith("/auth/") && chemin !== "/session") {
    window.dispatchEvent(new CustomEvent(EVENEMENT_SESSION_EXPIREE));
  }
  if (!reponse.ok) throw new ErreurApi(reponse.status, detailErreur(corps, reponse.status));
  // Le contrat est garanti par le schéma OpenAPI dont sont générés les types.
  return corps as T;
}

const id = encodeURIComponent;

const json = (methode: "POST", corps?: unknown): RequestInit => ({
  method: methode,
  headers: { "Content-Type": "application/json", Accept: "application/json" },
  ...(corps === undefined ? {} : { body: JSON.stringify(corps) }),
});

export const api = {
  session: () => requete<ContexteSession>("/session"),
  connexion: (identifiant: string, motDePasse: string) =>
    requete<Utilisateur>("/auth/connexion", json("POST", { identifiant, mot_de_passe: motDePasse })),
  deconnexion: () => requete<null>("/auth/deconnexion", json("POST")),

  clients: (filtres: { q?: string; type?: string; televendeur?: string } = {}) =>
    requete<Client[]>(url("/clients", filtres)),
  client360: (clientId: string) => requete<Client360>(`/clients/${id(clientId)}`),
  fiche: (clientId: string, mode?: ModeLLM, regenerer = false) =>
    requete<Fiche>(url(`/clients/${id(clientId)}/fiche`, { mode, regenerer: regenerer || undefined })),
  produit: (clientId: string, code: string) =>
    requete<DetailsProduit>(`/clients/${id(clientId)}/produits/${id(code)}`),

  fileAppels: (televendeur?: string) => requete<FileAppels>(url("/appels/file", { televendeur })),
  enregistrerCompteRendu: (saisie: SaisieCompteRendu) =>
    requete<CompteRenduEnregistre>("/comptes-rendus", json("POST", saisie)),
  comptesRendus: (filtres: { client_id?: string; jours?: number } = {}) =>
    requete<CompteRendu[]>(url("/comptes-rendus", filtres)),
  statistiques: (jours: number) => requete<StatistiquesAppels>(url("/statistiques", { jours })),

  planEcoulement: () => requete<PlanEcoulement>("/stock/plan-ecoulement"),

  diagnostic: () => requete<RapportDiagnostic>("/admin/diagnostic"),

  labo: {
    agent: (clientId: string) => requete<ConfigurationAgent>(url("/labo/agent", { client_id: clientId })),
    outils: (clientId: string, produit?: string) =>
      requete<ResultatOutilLabo[]>(url(`/labo/clients/${id(clientId)}/outils`, { produit })),
    comparaison: (clientId: string) =>
      requete<Partial<Record<ModeLLM, Fiche>>>(`/labo/clients/${id(clientId)}/comparaison`),
  },
};
