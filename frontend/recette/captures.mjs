// Recette visuelle : parcourt l'application comme un utilisateur et enregistre des captures.
//
//   URL_BASE=https://localhost IDENTIFIANTS='julie.moreau:motdepasse,responsable:motdepasse' \
//   node recette/captures.mjs etape-1 ../docs/captures/etape-1
//
// Nécessite `playwright-core` (devDependency) et un Chromium (CHROMIUM=/chemin/vers/chrome).

import { mkdirSync } from "node:fs";
import { join } from "node:path";
import { chromium } from "playwright-core";

const [scenario = "etape-1", dossier = "captures"] = process.argv.slice(2);
const base = process.env.URL_BASE ?? "http://localhost:8000";
const identifiants = Object.fromEntries(
  (process.env.IDENTIFIANTS ?? "").split(",").filter(Boolean).map((paire) => paire.split(":")),
);
mkdirSync(dossier, { recursive: true });

const MOBILE = { width: 390, height: 844, deviceScaleFactor: 2, isMobile: true, hasTouch: true };
const BUREAU = { width: 1366, height: 900, deviceScaleFactor: 1 };

const navigateur = await chromium.launch({ executablePath: process.env.CHROMIUM, args: ["--no-sandbox"] });

async function page(format) {
  const contexte = await navigateur.newContext({ viewport: { width: format.width, height: format.height }, ...format, ignoreHTTPSErrors: true, locale: "fr-FR" });
  return contexte.newPage();
}

async function capture(p, nom, pleinePage = true) {
  await p.waitForTimeout(400);
  // Sur mobile, la barre de navigation est fixe : on capture l'écran tel que vu par l'utilisateur.
  const mobile = (p.viewportSize()?.width ?? 1000) < 600;
  await p.screenshot({ path: join(dossier, `${nom}.png`), fullPage: pleinePage && !mobile });
  console.log(`capture : ${nom}.png`);
}

async function captureElement(p, selecteur, nom) {
  // En-tête et navigation fixes masqués le temps de la capture (sinon ils recouvrent l'élément).
  const style = await p.addStyleTag({ content: ".entete, .navigation { position: static !important; }" });
  const element = p.locator(selecteur).first();
  await element.scrollIntoViewIfNeeded();
  await p.waitForTimeout(300);
  await element.screenshot({ path: join(dossier, `${nom}.png`) });
  await style.evaluate((noeud) => noeud.remove()); // l'application garde ses éléments fixes pour la suite
  console.log(`capture : ${nom}.png`);
}

async function connecter(p, identifiant) {
  await p.goto(base + "/");
  await p.fill('input[name="identifiant"]', identifiant);
  await p.fill('input[name="mot_de_passe"]', identifiants[identifiant] ?? "");
  await p.click('button[type="submit"]');
  await p.waitForSelector(".navigation");
  await p.waitForSelector(".tuiles, .message-erreur", { timeout: 15000 });
}

const scenarios = {
  async "etape-1"() {
    const mobile = await page(MOBILE);
    await mobile.goto(base + "/");
    await mobile.waitForSelector('input[name="identifiant"]');
    await capture(mobile, "01-connexion-mobile", false);
    await mobile.fill('input[name="identifiant"]', "julie.moreau");
    await mobile.fill('input[name="mot_de_passe"]', "mauvais-mot-de-passe");
    await mobile.click('button[type="submit"]');
    await mobile.waitForSelector(".message-erreur");
    await capture(mobile, "02-connexion-refusee-mobile", false);

    await connecter(mobile, "julie.moreau");
    await capture(mobile, "03-file-televendeuse-mobile");
    await mobile.click(".tuiles a");
    await mobile.waitForSelector(".accroches");
    await capture(mobile, "04-fiche-televendeuse-mobile");
    await captureElement(mobile, "section.carte:has(form.formulaire)", "04b-compte-rendu-au-nom-de-la-televendeuse");

    const bureau = await page(BUREAU);
    await connecter(bureau, "responsable");
    await capture(bureau, "05-file-responsable-bureau", false);
    await bureau.goto(base + "/#/tableau-de-bord");
    await bureau.waitForSelector(".kpis");
    await capture(bureau, "06-tableau-de-bord-responsable", false);

    const vendeuse = await page(BUREAU);
    await connecter(vendeuse, "julie.moreau");
    await vendeuse.goto(base + "/#/tableau-de-bord");
    await vendeuse.waitForSelector(".titre-page");
    await capture(vendeuse, "07-mes-resultats-televendeuse", false);
  },

  // Copilote branché en HTTP sur le simulateur du datahub, avec anomalies injectées.
  async "etape-2"() {
    const bureau = await page(BUREAU);
    await connecter(bureau, "responsable");
    await bureau.goto(base + "/#/donnees");
    await bureau.waitForSelector(".statut-diagnostic", { timeout: 30000 });
    await capture(bureau, "01-donnees-diagnostic-bureau");

    // Détail de quelques règles : ce que l'équipe ERP doit corriger, et pourquoi.
    for (const libelle of ["Commande d'un client inconnu", "Lot périmé déclaré en stock", "Quantité anormale"]) {
      await bureau.locator("details.regle summary", { hasText: libelle }).click();
    }
    await captureElement(bureau, "section.carte:has(details.regle)", "02-regles-qualite-detaillees");

    const mobile = await page(MOBILE);
    await connecter(mobile, "responsable");
    await mobile.goto(base + "/#/donnees");
    await mobile.waitForSelector(".statut-diagnostic", { timeout: 30000 });
    await capture(mobile, "03-donnees-mobile", false);

    const vendeuse = await page(MOBILE);
    await connecter(vendeuse, "julie.moreau");
    await capture(vendeuse, "04-file-via-datahub-mobile", false);
    await vendeuse.click(".tuiles a");
    await vendeuse.waitForSelector(".accroches");
    await capture(vendeuse, "05-fiche-via-datahub-mobile", false);
    await vendeuse.goto(base + "/#/donnees");
    await vendeuse.waitForSelector(".message-erreur");
    await capture(vendeuse, "06-donnees-refusees-televendeuse", false);
  },

  // Banc d'évaluation, première campagne lancée depuis l'interface.
  async "etape-3"() {
    const bureau = await page(BUREAU);
    await connecter(bureau, "responsable");
    await bureau.goto(base + "/#/labo/qualite");
    await bureau.waitForSelector("text=Lancer l'évaluation");
    await capture(bureau, "01-qualite-ia-avant-evaluation", false);
    await bureau.click("text=Lancer l'évaluation");
    await bureau.waitForSelector("text=Évaluation en cours");
    await bureau.waitForTimeout(1500);
    await capture(bureau, "02-evaluation-en-cours", false);
    await bureau.waitForSelector(".score-redacteur", { timeout: 120000 });
  },

  // Après une seconde campagne (nouvelle version du prompt) : historique et détail.
  async "etape-3-historique"() {
    const bureau = await page(BUREAU);
    await connecter(bureau, "responsable");
    await bureau.goto(base + "/#/labo/qualite");
    await bureau.waitForSelector(".score-redacteur", { timeout: 30000 });
    await capture(bureau, "03-qualite-ia-resultats");
    await bureau.locator("details.regle summary").first().click();
    await captureElement(bureau, "section.carte:has(details.regle)", "04-detail-par-client");
    await captureElement(bureau, "section.carte:has(.barres-h)", "05-historique-versions-du-prompt");

    const mobile = await page(MOBILE);
    await connecter(mobile, "responsable");
    await mobile.goto(base + "/#/labo/qualite");
    await mobile.waitForSelector(".score-redacteur", { timeout: 30000 });
    await mobile.locator(".score-redacteur").first().scrollIntoViewIfNeeded();
    await capture(mobile, "06-qualite-ia-mobile", false);
  },

  // La journée du télévendeur : tournée, comptes-rendus, bilan, export, apprentissage.
  async "etape-4"() {
    const mobile = await page(MOBILE);
    await connecter(mobile, "julie.moreau");
    await mobile.waitForSelector(".carte.journee");
    await capture(mobile, "01-ma-journee-mobile", false);
    await captureElement(mobile, "section.carte:has(.sous-titre)", "02-agenda-des-rappels");

    await mobile.goto(base + "/#/");
    await mobile.waitForSelector(".carte.journee");
    await mobile.click("text=Démarrer la tournée");
    await mobile.waitForSelector(".bandeau-tournee");
    await mobile.waitForSelector(".accroches");
    await capture(mobile, "03-tournee-fiche-mobile", false);

    const accepter = mobile.locator(".ligne-cr .segment button.accepte");
    await accepter.nth(0).click();
    await accepter.nth(1).click();
    await mobile.click("form.formulaire button[type=submit]");
    await mobile.waitForSelector("text=Client suivant");
    await captureElement(mobile, "section.carte:has(.message-succes)", "04-compte-rendu-puis-client-suivant");

    await mobile.click("text=Client suivant");
    await mobile.waitForSelector(".bandeau-tournee");
    await mobile.waitForSelector("form.formulaire");
    await mobile.locator(".ligne-cr .segment button.accepte").first().click();
    await mobile.click("form.formulaire button[type=submit]");
    await mobile.waitForSelector("text=Client suivant");

    await mobile.goto(base + "/#/tournee/fin");
    await mobile.waitForSelector(".objectif");
    await capture(mobile, "05-bilan-de-tournee-mobile", false);
    const [telechargement] = await Promise.all([mobile.waitForEvent("download"), mobile.click("text=Commandes du jour (CSV)")]);
    await telechargement.saveAs(join(dossier, "commandes-du-jour.csv"));
    console.log("export : commandes-du-jour.csv");
  },

  async "etape-4-equipe"() {
    const bureau = await page(BUREAU);
    await connecter(bureau, "responsable");
    await bureau.waitForSelector(".carte.journee");
    await capture(bureau, "06-journee-equipe-bureau", false);
  },

  // Apprentissage des retours : une offre souvent acceptée, une souvent refusée par des clients du même type.
  async "etape-4-apprentissage"() {
    const bureau = await page(BUREAU);
    await connecter(bureau, "responsable");
    for (const [client, texte, nom] of [
      ["C016", "souvent accepté", "07-apprentissage-souvent-accepte"],
      ["C020", "souvent refusé", "08-apprentissage-souvent-refuse"],
    ]) {
      await bureau.goto(base + `/#/clients/${client}`);
      await bureau.waitForSelector(`text=${texte}`, { timeout: 30000 });
      await captureElement(bureau, `section.carte:has-text("${texte}")`, nom);
    }
  },

  // Multi-fournisseur : un service compatible OpenAI branché par la seule configuration, comparé aux autres rédacteurs.
  async "multi-fournisseur"() {
    const bureau = await page(BUREAU);
    await connecter(bureau, "responsable");
    await bureau.goto(base + "/#/clients/C005");
    await bureau.waitForSelector(".accroches", { timeout: 30000 });
    await captureElement(bureau, "section.carte:has(select)", "01-fiche-redigee-par-le-fournisseur-configure");
    await bureau.locator("summary:has-text(\"Coulisses de l'IA\")").click();
    await captureElement(bureau, "details:has-text(\"Coulisses de l'IA\")", "02-coulisses-appels-au-fournisseur");

    await bureau.goto(base + "/#/labo");
    await bureau.click("text=Comparer les rédacteurs");
    await bureau.waitForSelector(".comparaison", { timeout: 60000 });
    await capture(bureau, "03-labo-comparaison-des-redacteurs");

    await bureau.goto(base + "/#/labo/qualite");
    await bureau.waitForSelector("text=Lancer l'évaluation");
    await captureElement(bureau, "section.carte:has-text(\"Lancer l'évaluation\")", "04-banc-choix-des-redacteurs");
    await bureau.click("text=Lancer l'évaluation");
    await bureau.waitForSelector("text=Évaluation en cours");
    await bureau.waitForSelector("text=Évaluation en cours", { state: "detached", timeout: 180000 });
    await bureau.waitForSelector(".score-redacteur", { timeout: 30000 });
    await capture(bureau, "05-banc-scores-par-fournisseur");
  },
};

try {
  if (!scenarios[scenario]) throw new Error(`Scénario inconnu : ${scenario}`);
  await scenarios[scenario]();
} finally {
  await navigateur.close();
}
