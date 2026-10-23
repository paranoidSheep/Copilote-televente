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
  await p.addStyleTag({ content: ".entete, .navigation { position: static !important; }" });
  const element = p.locator(selecteur).first();
  await element.scrollIntoViewIfNeeded();
  await p.waitForTimeout(300);
  await element.screenshot({ path: join(dossier, `${nom}.png`) });
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
};

try {
  if (!scenarios[scenario]) throw new Error(`Scénario inconnu : ${scenario}`);
  await scenarios[scenario]();
} finally {
  await navigateur.close();
}
