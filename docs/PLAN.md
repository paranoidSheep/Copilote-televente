# Plan de développement — suite de la V2

Ce plan est suivi au fil de l'eau : chaque case est cochée quand l'élément est livré, testé et poussé. Chaque étape se termine par des captures d'écran (dans `docs/captures/`) et par un commit dédié.

| Étape | Objectif | Statut |
|---|---|---|
| 1 | Prêt pour le VPS : conteneur, HTTPS, comptes utilisateurs | ✅ livrée |
| 2 | Brancher le datahub sans attendre : simulateur REST et contrôle qualité des données | ✅ livrée |
| 3 | Mesurer la qualité de l'IA : banc d'évaluation | ⏳ en cours |
| 4 | La journée du télévendeur : mode tournée, rappels, apprentissage des retours | à faire |

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

- [ ] Critères mesurés par fiche :
  - corrections des garde-fous ;
  - couverture des signaux clés (décrochés, lots urgents habituels, rappel) ;
  - format (2 ou 3 accroches, contact cité, longueur) ;
  - latence, jetons et coût estimé
- [ ] Banc d'évaluation sur tous les clients, par rédacteur (`simule`, `repli`, `anthropic` si une clé est présente)
- [ ] Historique des évaluations (SQLite), pour comparer les versions du prompt
- [ ] Commande `python -m scripts.evaluer` et rapport (JSON et Markdown)
- [ ] Écran « Qualité IA » dans le labo : scores, comparaison des rédacteurs, détail par client
- [ ] Tests et captures

## Étape 4 — La journée du télévendeur

**Pourquoi.** Le copilote doit accompagner la séance d'appels du début à la fin, et ses propositions doivent s'améliorer avec les retours des clients.

- [ ] Mode tournée : enchaîner les fiches dans l'ordre de priorité, passer au client suivant après le compte-rendu, suivre la progression
- [ ] Agenda des rappels (aujourd'hui, en retard, à venir)
- [ ] Objectifs du jour (appels, CA accepté) avec progression
- [ ] Apprentissage des retours : le taux d'acceptation passé (par produit et type de client) module la pertinence des propositions de stock et des suggestions, avec une justification lisible
- [ ] Export CSV des commandes acceptées du jour (pour import manuel dans l'ERP)
- [ ] Tests et captures (tournée, agenda, objectifs)

---

## Journal de suivi

| Date | Étape | Livré |
|---|---|---|
| 23/10/2026 | — | Plan rédigé |
| 23/10/2026 | 1 | Docker + Caddy HTTPS, comptes et rôles, sessions signées, droits, journaux JSON, sauvegardes, guide VPS, 164 tests |
| 23/10/2026 | 2 | Simulateur REST, contrat OpenAPI, mise à l'écart des données inexploitables, diagnostic (écran, API, CLI), profil Docker `simulateur`, 208 tests |
