// Fichier GÉNÉRÉ par `python -m scripts.generer_types_ts` à partir du schéma OpenAPI.
// Ne pas modifier à la main : modifier les modèles pydantic puis relancer le script.

export interface AchatClient {
  date: string;
  quantite: number;
}

export interface AppelPrecedent {
  jour: string;
  televendeur: string;
  issue: Issue;
  notes: string;
  rappel_le: string | null;
  produits_acceptes: string[];
  produits_refuses: string[];
}

export interface CaMensuel {
  mois: string;
  ca_ht: number;
}

/** Une exécution du banc : tous les clients demandés, avec chaque rédacteur demandé. */
export interface Campagne {
  id: number | null;
  lancee_le: string;
  duree_ms: number;
  empreinte_prompt: string;
  source: string;
  date_donnees: string;
  syntheses: SyntheseRedacteur[];
  fiches: EvaluationFiche[];
}

/** Un client professionnel (restaurant, cantine, boulangerie…). */
export interface Client {
  id: string;
  nom: string;
  type: string;
  ville: string;
  contact: string;
  telephone: string;
  commercial: string;
}

/** Vue complète d'un client : identité, habitudes chiffrées et historique des appels. */
export interface Client360 {
  client: Client;
  habitudes: HabitudesClient;
  appels: HistoriqueAppels;
  comptes_rendus: CompteRendu[];
}

export interface ClientCible {
  client_id: string;
  nom: string;
  type: string;
  commercial: string;
  pertinence: Pertinence;
  raison: string;
  quantite_estimee: number;
}

export interface CompteCorrection {
  type: TypeCorrection;
  nombre: number;
}

export interface CompteDefaut {
  libelle: string;
  nombre: number;
}

/** Compte-rendu enregistré. */
export interface CompteRendu {
  client_id: string;
  issue: Issue;
  notes: string;
  rappel_le: string | null;
  mode_fiche: string | null;
  lignes: LigneCompteRendu_Output[];
  televendeur: string;
  id: number;
  cree_le: string;
}

export interface CompteRenduEnregistre {
  compte_rendu: CompteRendu;
  texte_saisie_erp: string;
}

export interface ConfigurationAgent {
  prompt_systeme: string;
  exemple_demande: string;
  outils: DefinitionOutil[];
}

/** Ce que l'interface doit savoir pour l'utilisateur connecté. */
export interface ContexteSession {
  utilisateur: Utilisateur;
  permissions: Permission[];
  authentification: boolean;
  version: string;
  source_donnees: string;
  date_du_jour: string;
  mode_par_defaut: ModeLLM;
  modes_disponibles: ModeDisponible[];
  televendeurs: string[];
}

export interface ControleFormat {
  libelle: string;
  reussi: boolean;
  detail: string;
}

export interface Correction {
  type: TypeCorrection;
  message: string;
  codes: string[];
}

export interface DefinitionOutil {
  nom: string;
  description: string;
  schema_entree: Record<string, JsonValue>;
}

export interface DemandeEvaluation {
  redacteurs: ModeLLM[];
  clients?: string[] | null;
}

export interface DetailsProduit {
  produit: Produit;
  client_id: string;
  nb_commandes_client: number;
  quantite_habituelle: number | null;
  rythme_jours: number | null;
  derniers_achats: AchatClient[];
  lots: LotDisponible[];
  situation_stock: SituationStock | null;
  pertinence: Pertinence;
  raison_pertinence: string;
  nb_clients_similaires_acheteurs: number;
  ventes_journalieres: number;
}

export interface EtapeTrace {
  type: TypeEtape;
  nom: string;
  debut_ms: number;
  duree_ms: number;
  resume: string;
  detail: string | null;
  jetons_entree: number | null;
  jetons_sortie: number | null;
  erreur: boolean;
}

export type EtatEvaluation = "en_cours" | "terminee" | "echouee";

/** Note d'une fiche, et tout ce qui l'explique. */
export interface EvaluationFiche {
  client_id: string;
  client_nom: string;
  redacteur: ModeLLM;
  modele: string | null;
  mode_obtenu: ModeFiche;
  repli_force: boolean;
  score_global: number;
  score_fidelite: number;
  score_couverture: number;
  score_format: number;
  corrections: Correction[];
  remises_hors_regle: string[];
  signaux: SignalCle[];
  controles_format: ControleFormat[];
  duree_ms: number;
  jetons_entree: number;
  jetons_sortie: number;
  cout_usd: number | null;
}

export interface Exemple {
  identifiant: string;
  detail: string;
}

export type Famille = "frais" | "surgele";

export interface Fiche {
  client: Client;
  date_du_jour: string;
  genere_le: string;
  mode: ModeFiche;
  modele: string | null;
  avertissement: string | null;
  resume_habitudes: string;
  habitudes: HabitudesClient;
  produits_manquants: ManquantFiche[];
  stock_a_ecouler: StockFiche[];
  suggestions: SuggestionFiche[];
  accroches: string[];
  points_attention: string[];
  appels_precedents: HistoriqueAppels;
  panier: PanierPropose;
  garde_fous: Correction[];
  trace: TraceExecution | null;
  texte: string;
}

export interface FileAppels {
  date_du_jour: string;
  appels: PrioriteAppel[];
}

export type Gravite = "critique" | "alerte" | "info";

export interface HabitudesClient {
  client: Client;
  date_du_jour: string;
  periode_analysee_jours: number;
  nb_commandes: number;
  premiere_commande: string | null;
  derniere_commande: string | null;
  jours_depuis_derniere_commande: number | null;
  intervalle_median_jours: number | null;
  commandes_par_semaine: number;
  jours_habituels: JourSemaine[];
  prochain_jour_habituel: string | null;
  panier_moyen_ht: number | null;
  ca_total_ht: number;
  tendance_ca_pct: number | null;
  ca_mensuel: CaMensuel[];
  repartition_categories: PartCategorie[];
  produits_recurrents: ProduitRecurrent[];
}

export interface HistoriqueAppels {
  client_id: string;
  appels: AppelPrecedent[];
  codes_refuses_recemment: string[];
  rappel_prevu: string | null;
}

export interface Identifiants {
  identifiant: string;
  mot_de_passe: string;
}

/** Issue de l'appel. */
export type Issue = "commande" | "pas_de_besoin" | "rappeler" | "injoignable";

export type JourSemaine = "lundi" | "mardi" | "mercredi" | "jeudi" | "vendredi" | "samedi" | "dimanche";

export type JsonValue = unknown;

export interface LigneCompteRendu_Input {
  code: string;
  libelle: string;
  unite?: string;
  origine: Origine;
  reponse: Reponse;
  quantite: number;
  prix_unitaire_ht: number;
  remise_pct?: number;
}

export interface LigneCompteRendu_Output {
  code: string;
  libelle: string;
  unite: string;
  origine: Origine;
  reponse: Reponse;
  quantite: number;
  prix_unitaire_ht: number;
  remise_pct: number;
}

export interface LigneEcoulement {
  situation: SituationStock;
  clients: ClientCible[];
  quantite_potentielle: number;
  couverture_plan_pct: number;
  valeur_lot_ht: number;
}

export interface LignePanier {
  code: string;
  libelle: string;
  unite: string;
  origine: Origine;
  quantite: number;
  prix_unitaire_ht: number;
  remise_pct: number;
  prix_net_ht: number;
  montant_ht: number;
}

export interface LotDisponible {
  id: string;
  quantite: number;
  dlc: string;
  jours_avant_dlc: number;
}

export interface ManquantFiche {
  code: string;
  libelle: string;
  unite: string;
  prix_unitaire_ht: number;
  frequence_pct: number;
  rythme_habituel_jours: number;
  derniere_commande: string;
  jours_depuis_derniere_commande: number;
  quantite_habituelle: number;
  retard_ratio: number;
  statut: StatutManquant;
  commentaire: string;
}

/** Lecture d'une ressource du datahub : durée et volume (ou erreur). */
export interface MesureRessource {
  ressource: string;
  libelle: string;
  duree_ms: number;
  volume: number | null;
  erreur: string | null;
}

export interface ModeDisponible {
  mode: ModeLLM;
  libelle: string;
  modele: string | null;
}

export type ModeFiche = "ia" | "ia_simulee" | "repli";

/** Qui rédige la fiche d'appel. */
export type ModeLLM = "auto" | "anthropic" | "simule" | "repli";

export type MotifEcoulement = "dlc_courte" | "surstock";

export type NiveauPriorite = "haute" | "moyenne" | "basse";

/** D'où vient la proposition faite au client. */
export type Origine = "manquant" | "stock" | "suggestion" | "autre";

/** Proposition de commande à valider avec le client, à saisir ensuite dans l'ERP. */
export interface PanierPropose {
  lignes: LignePanier[];
  total_ht: number;
}

export interface PartCategorie {
  categorie: string;
  part_pct: number;
}

export type Permission = "voir_toutes_les_files" | "voir_statistiques_globales" | "utiliser_le_labo" | "diagnostiquer_les_donnees";

/** Intérêt d'un produit pour un client donné (plus c'est haut, plus c'est pertinent). */
export type Pertinence = 0 | 1 | 2 | 3;

export interface PlanEcoulement {
  date_du_jour: string;
  lignes: LigneEcoulement[];
  valeur_a_risque_ht: number;
  nb_lots_urgents: number;
}

export interface PrioriteAppel {
  client: Client;
  score: number;
  niveau: NiveauPriorite;
  raisons: RaisonPriorite[];
  jours_habituels: JourSemaine[];
  prochain_jour_habituel: string | null;
  jours_depuis_derniere_commande: number | null;
  panier_moyen_ht: number | null;
  nb_manquants: number;
  nb_decroches: number;
  nb_opportunites_stock: number;
  deja_appele_aujourdhui: boolean;
  rappel_prevu: string | null;
}

/** Un article du catalogue. */
export interface Produit {
  code: string;
  libelle: string;
  categorie: string;
  famille: Famille;
  unite: string;
  prix_unitaire_ht: number;
  duree_vie_jours: number;
}

export interface ProduitRecurrent {
  code: string;
  libelle: string;
  unite: string;
  frequence_pct: number;
  nb_commandes: number;
  quantite_habituelle: number;
  derniere_commande: string;
}

export interface RaisonPriorite {
  code: string;
  libelle: string;
  points: number;
}

export interface RapportDiagnostic {
  source: string;
  date_reference: string;
  genere_le: string;
  duree_totale_ms: number;
  periode_analyse_jours: number;
  statut: StatutDiagnostic;
  resume: string;
  connexion: MesureRessource[];
  contrat: VerificationContrat[];
  volumes: Volumes | null;
  qualite: ResultatRegle[];
  enregistrements_ecartes: number;
}

export type Reponse = "accepte" | "refuse" | "sans_reponse";

export interface ResultatOutilLabo {
  nom: string;
  arguments: Record<string, JsonValue>;
  est_erreur: boolean;
  resultat: JsonValue;
}

/** Résultat d'une règle de qualité, avec quelques exemples à corriger. */
export interface ResultatRegle {
  code: string;
  libelle: string;
  gravite: Gravite;
  traitement: Traitement;
  impact: string;
  nombre: number;
  exemples: Exemple[];
}

/** Une campagne de l'historique, sans le détail par fiche. */
export interface ResumeCampagne {
  id: number;
  lancee_le: string;
  duree_ms: number;
  empreinte_prompt: string;
  source: string;
  date_donnees: string;
  nb_clients: number;
  syntheses: SyntheseRedacteur[];
}

export type Role = "televendeur" | "responsable" | "admin";

/** Compte-rendu tel que saisi dans l'interface (l'auteur est l'utilisateur connecté). */
export interface SaisieCompteRendu {
  client_id: string;
  issue: Issue;
  notes?: string;
  rappel_le?: string | null;
  mode_fiche?: string | null;
  lignes?: LigneCompteRendu_Input[];
}

/** État public du service (sonde de supervision) : ne divulgue aucune donnée métier. */
export interface Sante {
  statut: string;
  version: string;
}

export interface SignalCle {
  type: TypeSignal;
  libelle: string;
  code: string | null;
  couvert: boolean;
}

/** Un produit à écouler, avec son lot prioritaire (DLC la plus proche). */
export interface SituationStock {
  code: string;
  libelle: string;
  categorie: string;
  famille: Famille;
  unite: string;
  motifs: MotifEcoulement[];
  lot_id: string;
  quantite_lot: number;
  dlc: string;
  jours_avant_dlc: number;
  stock_total: number;
  couverture_jours: number | null;
  prix_unitaire_ht: number;
  remise_suggeree_pct: number;
  prix_remise_ht: number;
}

export interface StatJour {
  jour: string;
  appels: number;
  ca_accepte_ht: number;
}

export interface StatOrigine {
  origine: Origine;
  proposes: number;
  acceptes: number;
  taux_acceptation_pct: number | null;
  ca_accepte_ht: number;
}

export interface StatProduit {
  code: string;
  libelle: string;
  proposes: number;
  acceptes: number;
}

export interface StatTelevendeur {
  televendeur: string;
  appels: number;
  commandes: number;
  ca_accepte_ht: number;
}

export interface StatistiquesAppels {
  nb_appels: number;
  nb_clients: number;
  issues: Partial<Record<Issue, number>>;
  taux_transformation_pct: number | null;
  ca_accepte_ht: number;
  quantite_stock_ecoulee: number;
  par_origine: StatOrigine[];
  par_televendeur: StatTelevendeur[];
  par_jour: StatJour[];
  produits_les_plus_acceptes: StatProduit[];
}

export type StatutDiagnostic = "conforme" | "a_surveiller" | "a_corriger" | "lecture_impossible";

export type StatutManquant = "en_retard" | "decroche";

export interface StockFiche {
  code: string;
  libelle: string;
  categorie: string;
  famille: Famille;
  unite: string;
  motifs: MotifEcoulement[];
  lot_id: string;
  quantite_lot: number;
  dlc: string;
  jours_avant_dlc: number;
  stock_total: number;
  couverture_jours: number | null;
  prix_unitaire_ht: number;
  remise_suggeree_pct: number;
  prix_remise_ht: number;
  pertinence: Pertinence;
  raison_pertinence: string;
  remise_pct: number;
  prix_propose_ht: number;
  quantite_conseillee: number;
  argument: string;
}

export interface SuggestionFiche {
  code: string;
  libelle: string;
  categorie: string;
  unite: string;
  prix_unitaire_ht: number;
  nb_clients_similaires_acheteurs: number;
  taux_adoption_pct: number;
  en_stock_a_ecouler: boolean;
  argument: string;
}

/** Avancement de la campagne lancée depuis l'interface (exécutée en arrière-plan). */
export interface SuiviEvaluation {
  etat: EtatEvaluation;
  redacteurs: ModeLLM[];
  faites: number;
  total: number;
  lancee_le: string;
  campagne_id: number | null;
  erreur: string | null;
}

/** Moyennes et totaux d'un rédacteur sur l'ensemble des clients évalués. */
export interface SyntheseRedacteur {
  redacteur: ModeLLM;
  modele: string | null;
  nb_fiches: number;
  score_global: number;
  score_fidelite: number;
  score_couverture: number;
  score_format: number;
  fiches_sans_defaut: number;
  taux_repli_pct: number;
  corrections: CompteCorrection[];
  remises_hors_regle: number;
  signaux_couverts: number;
  signaux_total: number;
  defauts_format: CompteDefaut[];
  latence_mediane_ms: number;
  latence_p95_ms: number;
  jetons_entree_moyens: number;
  jetons_sortie_moyens: number;
  cout_total_usd: number | null;
  cout_par_fiche_usd: number | null;
  cout_projete: boolean;
}

export interface TraceExecution {
  fournisseur: string;
  modele: string;
  etapes: EtapeTrace[];
  duree_totale_ms: number;
}

export type Traitement = "ecarte" | "signale";

/** Nature d'une correction appliquée par les garde-fous à la rédaction de l'IA. */
export type TypeCorrection = "produit_inconnu" | "offre_refusee" | "remise_plafonnee" | "selection_limitee" | "stock_complete" | "accroche_retiree" | "accroches_limitees" | "accroches_completees" | "rappel_ajoute";

export type TypeEtape = "appel_llm" | "outil" | "garde_fou";

/** Faits que toute bonne fiche doit faire ressortir. */
export type TypeSignal = "manquant_prioritaire" | "lot_urgent_habituel" | "rappel_promis";

/** Compte tel qu'exposé à l'application (jamais le hachage du mot de passe). */
export interface Utilisateur {
  identifiant: string;
  nom_affiche: string;
  role: Role;
  actif: boolean;
  cree_le: string;
}

/** Un point du contrat d'interface vérifié sur la source réelle. */
export interface VerificationContrat {
  libelle: string;
  reussie: boolean;
  detail: string;
}

export interface Volumes {
  clients: number;
  produits: number;
  commandes: number;
  lignes: number;
  lots: number;
  premiere_commande: string | null;
  derniere_commande: string | null;
}
