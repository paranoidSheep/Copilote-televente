# Plan de développement — suite de la V2

Ce plan est suivi au fil de l'eau : chaque case est cochée quand l'élément est livré, testé et poussé. Chaque étape se termine par des captures d'écran (dans `docs/captures/`) et par un commit dédié.

| Étape | Objectif | Statut |
|---|---|---|
| 1 | Prêt pour le VPS : conteneur, HTTPS, comptes utilisateurs | ✅ livrée |
| 2 | Brancher le datahub sans attendre : simulateur REST et contrôle qualité des données | ✅ livrée |
| 3 | Mesurer la qualité de l'IA : banc d'évaluation | ✅ livrée |
| 4 | La journée du télévendeur : mode tournée, rappels, apprentissage des retours | ✅ livrée |
| + | Multi-fournisseur : changer de fournisseur d'IA par simple configuration (demande complémentaire) | ✅ livrée |

---

## Étape 1 — Prêt pour le VPS

**Pourquoi.** L'application va être installée sur un serveur exposé à Internet. Elle doit s'installer en une commande, servir en HTTPS et n'être accessible qu'aux personnes autorisées. Le télévendeur connecté devient aussi l'auteur des comptes-rendus, au lieu d'un choix dans une liste.

- [x] Image Docker multi-étapes (compilation TypeScript, puis image Python légère, utilisateur non root)
- [x] `docker-compose.yml` : copilote + Caddy (HTTPS automatique Let's Encrypt), volume persistant `/data`
- [x] Comptes utilisateurs : rôles `televendeur`, `responsable` et `admin`, mots de passe hachés (scrypt), stockage SQLite
- [x] Sessions par cookie signé (HttpOnly, SameSite, Secure en HTTPS), page de connexion, déconnexion
- [x] Contrôle d'accès : toutes les routes protégées ; labo et suivi global réservés aux responsables ; un télévendeur ne voit que sa file
- [x] Le compte-rendu est attribué automatiquement à l'utilisateur connecté
- [x] Commandes d'administration : créer un utilisateur, réinitialiser un mot de passe, lister les comptes
- [x] Santé (`/sante`), journaux structurés, script de sauvegarde du journal SQLite
- [x] Guide `docs/DEPLOIEMENT.md` pas à pas (VPS Debian/Ubuntu)
- [x] Tests (authentification, droits, attribution) et captures (connexion, file d'un télévendeur)

**Livré.** L'image Docker est construite et la pile `docker compose` (copilote + Caddy) a été testée de bout en bout en HTTPS : sonde `/sante`, 401 sans session, en-têtes de sécurité, comptes créés dans le conteneur, données persistées dans le volume. Les captures sont dans [`captures/etape-1/`](captures/etape-1/).

## Étape 2 — Brancher le datahub sans attendre

**Pourquoi.** Le vrai datahub n'est pas encore accessible, mais le chemin `DATASOURCE=http` doit être éprouvé dès maintenant. Il faut aussi donner à l'équipe du datahub un contrat précis, et pouvoir diagnostiquer les données dès le premier branchement.

- [x] Simulateur de datahub REST (pagination, jeton, filtres), alimenté par le jeu fictif
- [x] Test d'intégration de bout en bout : `HttpDataSource` → simulateur → analyses → fiche
- [x] Contrat d'interface exporté en OpenAPI (`docs/contrat-datahub.json`), à transmettre à l'équipe datahub
- [x] Diagnostic de connexion : temps de réponse et volumes par ressource
- [x] Contrôle qualité des données : références orphelines, prix nuls, DLC incohérentes, doublons, clients sans télévendeur…
- [x] Écran « Données » (réservé aux responsables) et endpoint `/admin/diagnostic`
- [x] Tests et captures (diagnostic avec anomalies détectées)

**Livré.**
- **Simulateur.** Le simulateur (`python -m copilote.datahub.simulateur`) sert le jeu fictif selon le contrat REST : jeton, pagination `{items, next}`, filtres `client_id` et `depuis`. Ses options `--anomalies` et `--latence-ms` injectent des défauts réalistes et simulent le réseau.
- **Contrat.** Le contrat est rédigé pour l'équipe du datahub ([`CONTRAT-DATAHUB.md`](CONTRAT-DATAHUB.md)), avec sa version OpenAPI, vérifiée par la CI.
- **Robustesse.** En branchant le simulateur avec anomalies, le plan d'écoulement plantait sur une commande d'un client inconnu. Le copilote écarte désormais les données inexploitables au chargement (doublons, références orphelines, commandes futures, lots périmés) et en garde la trace.
- **Diagnostic.** Le diagnostic (écran « Données », `GET /admin/diagnostic`, `python -m copilote.diagnostic`) couvre la connexion, 5 points du contrat et 15 règles de qualité, avec les identifiants ERP à corriger.
- **Vérification.** La pile Docker a été testée avec le profil `simulateur`, en HTTPS. Les tests vérifient que la fiche obtenue par HTTP est strictement identique à celle du mock. Les captures sont dans [`captures/etape-2/`](captures/etape-2/).

## Étape 3 — Mesurer la qualité de l'IA

**Pourquoi.** Avant de passer à Claude en production, et à chaque modification du prompt, il faut pouvoir mesurer objectivement la qualité des fiches, et non en juger « à l'œil ».

- [x] Critères mesurés par fiche :
  - corrections des garde-fous ;
  - couverture des signaux clés (décrochés, lots urgents habituels, rappel) ;
  - format (2 ou 3 accroches, contact cité, longueur) ;
  - latence, jetons et coût estimé
- [x] Banc d'évaluation sur tous les clients, par rédacteur (`simule`, `repli`, `anthropic` si une clé est présente)
- [x] Historique des évaluations (SQLite), pour comparer les versions du prompt
- [x] Commande `python -m scripts.evaluer` et rapport (JSON et Markdown)
- [x] Écran « Qualité IA » dans le labo : scores, comparaison des rédacteurs, détail par client
- [x] Tests et captures

**Livré.**
- **Garde-fous typés.** Chaque correction (`TypeCorrection`) est pondérée selon sa gravité ; les critères sont des fonctions pures, sans IA juge.
- **Banc.** Les campagnes tournent en arrière-plan, quatre fiches à la fois, hors cache. Elles sont historisées avec l'empreinte du prompt. Rapport Markdown, garde-fou en CI (`--score-minimum 85`).
- **Ce que le banc a révélé, puis corrigé :**
  - le repli ne saluait pas l'interlocuteur quand le client n'avait aucun produit en retard ;
  - quand un garde-fou retirait une offre refusée, l'accroche qui la vantait restait en place : le télévendeur aurait annoncé au téléphone une remise sur un produit refusé. Un nouveau garde-fou retire désormais ces accroches ;
  - l'IA laisse souvent de côté les lots à DLC imminente d'un produit que le client achète. Le prompt les rend désormais prioritaires ; l'effet est à mesurer avec Claude, puisque l'IA simulée rejoue des réponses enregistrées.
- **Captures.** Elles sont dans [`captures/etape-3/`](captures/etape-3/).

## Étape 4 — La journée du télévendeur

**Pourquoi.** Le copilote doit accompagner la séance d'appels du début à la fin, et ses propositions doivent s'améliorer avec les retours des clients.

- [x] Mode tournée : enchaîner les fiches dans l'ordre de priorité, passer au client suivant après le compte-rendu, suivre la progression
- [x] Agenda des rappels (aujourd'hui, en retard, à venir)
- [x] Objectifs du jour (appels, CA accepté) avec progression
- [x] Apprentissage des retours : le taux d'acceptation passé (par produit et type de client) module la pertinence des propositions de stock et des suggestions, avec une justification lisible
- [x] Export CSV des commandes acceptées du jour (pour import manuel dans l'ERP)
- [x] Tests et captures (tournée, agenda, objectifs)

**Livré.**
- **Journée.** « Appels du jour » ouvre sur la journée : objectifs (appels, CA accepté), tournée, agenda des rappels et export CSV. Un responsable voit la journée de l'équipe, avec des objectifs cumulés.
- **Tournée.** Elle ne stocke aucun état : elle se déduit de la file d'appels et du journal. Un bandeau suit la progression, avec « Passer ce client » ; après chaque compte-rendu, « Client suivant » ; un bilan la termine.
- **Apprentissage.** Taux lissé par produit et type d'établissement (au moins 3 propositions), modulation d'une demi-marche, justification visible dans la fiche et transmise à l'IA.
- **Export CSV.** Prévu pour Excel en français (séparateur « ; », virgule décimale, UTF-8 avec BOM), avec neutralisation des formules. Un télévendeur n'exporte que ses commandes.
- **Captures.** Elles sont dans [`captures/etape-4/`](captures/etape-4/) : tournée sur mobile, bilan, export ouvert dans un tableur, journée de l'équipe, apprentissage.

## Complément — Multi-fournisseur d'IA

**Pourquoi.** Ne pas dépendre d'un seul fournisseur : pouvoir changer de modèle selon le prix, la qualité mesurée ou l'hébergement des données (Europe, serveurs internes), sans toucher au code.

- [x] Catalogue des fournisseurs : Claude, Mistral, OpenAI, Gemini, et tout service compatible OpenAI (Ollama, vLLM, LM Studio…)
- [x] Configuration par variables d'environnement, plusieurs fournisseurs à la fois, `LLM_MODE=auto` par ordre de préférence, avertissements au démarrage
- [x] Adaptateur « Chat Completions » (SDK officiel `openai`), à côté de l'adaptateur Claude, avec erreurs traduites pour le télévendeur
- [x] Fournisseurs comparables partout : choix du rédacteur dans la fiche, comparaison dans le labo, banc d'évaluation avec coût aux prix configurés
- [x] Simulateur de service compatible OpenAI, pour éprouver le branchement sans clé (tests de bout en bout sur le réseau, profil Docker `simulateur`)
- [x] Service Ollama facultatif dans Docker (profil `ollama`) pour un modèle local
- [x] Tests et captures

**Livré.**
- **Changer de fournisseur** se fait dans `.env` : clé, modèle, éventuellement adresse, puis `LLM_MODE`. Seul Claude a un modèle par défaut ; pour les autres, le nom du modèle est exigé, car les catalogues changent vite.
- **Vérifié contre les vraies API** avec une clé volontairement invalide : Gemini répond et l'erreur est traduite (« clé d'API Gemini (Google) refusée ») ; ce test a révélé un format d'erreur propre à Gemini, désormais géré. Mistral et OpenAI ne sont pas joignables depuis l'environnement de développement (politique réseau) : à vérifier sur le VPS avec de vraies clés.
- **Captures.** Elles sont dans [`captures/multi-fournisseur/`](captures/multi-fournisseur/) : fiche rédigée par le fournisseur configuré, coulisses des appels, comparaison des rédacteurs dans le labo, banc d'évaluation par fournisseur.

---

## Journal de suivi

| Date | Étape | Livré |
|---|---|---|
| 23/10/2026 | — | Plan rédigé |
| 23/10/2026 | 1 | Docker + Caddy HTTPS, comptes et rôles, sessions signées, droits, journaux JSON, sauvegardes, guide VPS, 164 tests |
| 23/10/2026 | 2 | Simulateur REST, contrat OpenAPI, mise à l'écart des données inexploitables, diagnostic (écran, API, CLI), profil Docker `simulateur`, 208 tests |
| 23/10/2026 | 3 | Corrections typées, banc d'évaluation (critères, historique, écran Qualité IA, CLI, CI), 2 défauts corrigés et 1 amélioration du prompt, 233 tests |
| 23/10/2026 | 4 | Journée (objectifs, agenda, tournée), apprentissage des retours clients, export CSV pour l'ERP, 244 tests |
| 23/10/2026 | + | Multi-fournisseur : catalogue, adaptateur Chat Completions, configuration, simulateur compatible OpenAI, profils Docker `simulateur` et `ollama`, 266 tests |
