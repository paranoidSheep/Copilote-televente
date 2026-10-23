# Déployer le copilote sur un VPS

Ce guide installe le copilote sur un serveur Linux (Debian 12 ou Ubuntu 22.04/24.04). Il sera servi en HTTPS sur votre nom de domaine. Compter environ 15 minutes.

```
Internet ──HTTPS──▶ Caddy (certificat Let's Encrypt automatique) ──▶ copilote:8000 (réseau Docker interne)
                                                                       └─ volume « donnees » : comptes, journal, sauvegardes
```

## 1. Prérequis

- Un VPS avec 1 vCPU, 1 Go de RAM et 10 Go de disque (largement suffisant).
- Un nom de domaine (ou sous-domaine), par exemple `copilote.mon-entreprise.fr`, avec un enregistrement DNS **A** (et **AAAA** si IPv6) pointant vers l'adresse IP du VPS.
- Les ports **80** et **443** ouverts : Let's Encrypt a besoin du port 80 pour délivrer le certificat.

## 2. Installer Docker

```bash
curl -fsSL https://get.docker.com | sudo sh
sudo usermod -aG docker $USER   # puis se déconnecter et se reconnecter
docker compose version          # vérification
```

## 3. Récupérer le copilote et le configurer

```bash
git clone https://github.com/paranoidSheep/Copilote-televente.git
cd Copilote-televente
cp .env.production.example .env
python3 -c "import secrets; print(secrets.token_urlsafe(48))"   # à coller dans SESSION_SECRET
nano .env
```

Variables à renseigner au minimum :

| Variable | Exemple | Rôle |
|---|---|---|
| `DOMAINE` | `copilote.mon-entreprise.fr` | Nom de domaine du site (certificat HTTPS) |
| `EMAIL_ACME` | `admin@mon-entreprise.fr` | Compte Let's Encrypt (alertes d'expiration) |
| `SESSION_SECRET` | 64 caractères aléatoires | Signature des sessions : **obligatoire**, à garder secret |
| `ANTHROPIC_API_KEY`, `MISTRAL_API_KEY`… | `sk-ant-…` | Facultatif : sans fournisseur d'IA configuré, l'IA simulée est utilisée (voir ci-dessous) |

> Le fichier `.env` contient des secrets : il ne doit jamais être versionné. Il est déjà exclu par `.gitignore`.

### Choisir le fournisseur d'IA

Le copilote fonctionne avec Claude, Mistral, OpenAI, Gemini ou un modèle local. On renseigne dans `.env` les variables du ou des fournisseurs retenus (le fichier d'exemple les liste toutes), et `LLM_MODE` désigne celui qui rédige les fiches par défaut :

```bash
# Exemple : Mistral par défaut, Claude disponible pour comparer dans le Labo
LLM_MODE=mistral
MISTRAL_API_KEY=...
MISTRAL_MODEL=mistral-medium-latest
ANTHROPIC_API_KEY=sk-ant-...
```

Après modification : `docker compose up -d` (le conteneur redémarre avec la nouvelle configuration). Au démarrage, `docker compose logs copilote` signale un fournisseur à moitié configuré.

**Essayer sans clé.** Le profil `simulateur` démarre aussi un service d'IA compatible OpenAI simulé, qui rejoue les rédactions de démonstration. Avec dans `.env` : `LLM_COMPATIBLE_BASE_URL=http://ia-simulateur:8200/v1`, `LLM_COMPATIBLE_MODEL=cassettes`, `LLM_COMPATIBLE_NOM=Simulateur OpenAI`, puis `docker compose --profile simulateur up -d`, le rédacteur « Simulateur OpenAI » apparaît dans la fiche et le labo : c'est exactement le chemin qu'emprunteront Mistral, OpenAI, Gemini ou Ollama.

**Modèle local, sans envoi de données à l'extérieur.** Le service Ollama facultatif tourne sur le VPS, dans le réseau interne :

```bash
docker compose --profile ollama up -d
docker compose exec ollama ollama pull qwen3      # un modèle qui sait appeler des outils
```

puis dans `.env` : `LLM_MODE=compatible`, `LLM_COMPATIBLE_BASE_URL=http://ollama:11434/v1`, `LLM_COMPATIBLE_MODEL=qwen3`, `LLM_COMPATIBLE_NOM=Ollama`. Sans carte graphique, un modèle de quelques milliards de paramètres rédige une fiche en une à plusieurs minutes : le banc d'évaluation (section 9) dit si la qualité suit.

## 4. Démarrer

```bash
docker compose up -d --build
docker compose ps        # « copilote » doit être « healthy », « caddy » « Up »
```

Au premier démarrage, Caddy obtient le certificat HTTPS en quelques secondes. Le site répond alors sur `https://DOMAINE` et affiche la page de connexion.

## 5. Créer les comptes

Un compte de démonstration par télévendeur présent dans les données, plus un responsable :

```bash
docker compose exec copilote python -m copilote.admin demo
```

Les mots de passe sont générés aléatoirement et **affichés une seule fois**.

Pour créer un compte nominatif :

```bash
docker compose exec copilote python -m copilote.admin creer julie.moreau --nom "Julie Moreau" --role televendeur
docker compose exec copilote python -m copilote.admin lister
docker compose exec copilote python -m copilote.admin mot-de-passe julie.moreau   # ferme ses sessions ouvertes
docker compose exec copilote python -m copilote.admin desactiver julie.moreau
```

| Rôle | Accès |
|---|---|
| `televendeur` | Sa file d'appels, toutes les fiches, ses comptes-rendus, ses résultats |
| `responsable` | Toutes les files, statistiques globales, labo IA, écran « Données » (diagnostic) |
| `admin` | Comme responsable |

> Pour un télévendeur, le **nom affiché** doit être identique au champ « commercial » des clients dans l'ERP : c'est ce lien qui lui attribue sa file d'appels.

Pour une démonstration avec un historique d'appels fictif :

```bash
docker compose exec copilote python -m scripts.peupler_journal_demo --vider
```

## 6. Sauvegardes

Le journal des comptes-rendus et les comptes sont dans le volume Docker `donnees`. Pour en faire une sauvegarde à chaud, cohérente même pendant l'utilisation :

```bash
docker compose exec copilote python -m scripts.sauvegarder --garder 14
```

Les sauvegardes sont écrites dans `/data/sauvegardes` (dans le volume). Pour les planifier chaque nuit et en garder une copie hors du serveur :

```bash
crontab -e
# 03:15 chaque nuit : sauvegarde, puis copie hors du conteneur
15 3 * * * cd /chemin/Copilote-televente && docker compose exec -T copilote python -m scripts.sauvegarder && docker compose cp copilote:/data/sauvegardes ./sauvegardes
```

## 7. Mettre à jour

```bash
git pull
docker compose up -d --build     # les données (volume) sont conservées
```

## 8. Brancher le datahub

### Essayer d'abord avec le simulateur

Le simulateur du datahub tourne dans un conteneur à part, sur le réseau interne. Il permet de tester le chemin `DATASOURCE=http` de bout en bout, et de voir le diagnostic des données à l'œuvre. Dans `.env` :

```bash
DATASOURCE=http
DATAHUB_URL=http://datahub-simulateur:8100
DATAHUB_TOKEN=un-jeton-au-choix
DATAHUB_DATE_REFERENCE=2026-10-23     # date du jeu de données fictif
SIMULATEUR_OPTIONS=--anomalies        # facultatif : défauts de données réalistes
```

Puis :

```bash
docker compose --profile simulateur up -d
docker compose exec copilote python -m copilote.diagnostic
```

L'en-tête de l'application affiche « données http ». L'écran **Données** (responsables) présente le même diagnostic.

### Le vrai datahub

Transmettre à l'équipe du datahub le contrat d'interface [`CONTRAT-DATAHUB.md`](CONTRAT-DATAHUB.md). Une fois l'accès obtenu, dans `.env` :

```bash
DATASOURCE=http
DATAHUB_URL=https://datahub.mon-entreprise.local/api/v1
DATAHUB_TOKEN=…                       # jeton en lecture seule
# DATAHUB_DATE_REFERENCE à supprimer : la date du jour réelle est utilisée
```

```bash
docker compose up -d                  # sans le profil simulateur
docker compose exec copilote python -m copilote.diagnostic
```

Code de sortie du diagnostic : `0` conforme, `1` corrections nécessaires, `2` lecture impossible (datahub injoignable, jeton refusé, réponse non conforme). Les anomalies listées sont à corriger dans l'ERP. En attendant, le copilote écarte automatiquement les enregistrements inexploitables (doublons, références orphelines, lots périmés…).

## 9. Mesurer la qualité de l'IA

Le banc d'évaluation note les fiches de tous les clients. Il se lance depuis **Labo › Qualité IA** (responsables), ou en ligne de commande :

```bash
docker compose exec copilote python -m scripts.evaluer                        # IA simulée et repli
docker compose exec copilote python -m scripts.evaluer --redacteurs anthropic # Claude (nécessite ANTHROPIC_API_KEY, facturé)
docker compose exec copilote python -m scripts.evaluer --redacteurs anthropic,mistral,compatible   # comparer les fournisseurs configurés
```

Les campagnes sont conservées dans le volume (`/data/evaluations.sqlite3`, rapports dans `/data/evaluations/`). Avec Claude, prévoir quelques minutes et environ un centime de dollar par fiche : le coût exact estimé figure dans le rapport. Pour les autres fournisseurs, le coût n'est estimé que si leurs prix sont renseignés (`MISTRAL_PRIX_ENTREE`, `MISTRAL_PRIX_SORTIE`…).

## 10. Supervision et journaux

```bash
docker compose logs -f copilote                                   # une ligne JSON par requête (utilisateur, route, statut, durée)
docker compose logs copilote | grep '"statut": 401'               # tentatives d'accès non authentifiées
docker compose logs copilote | grep "Échec de connexion"           # mots de passe erronés
curl -s https://DOMAINE/sante                                      # sonde publique : {"statut":"ok", ...}
```

## Sécurité : ce qui est en place

- **HTTPS** obligatoire (Caddy, HSTS). Le copilote n'est jamais exposé directement : il n'est joignable que par Caddy, sur le réseau Docker interne.
- **Mots de passe** hachés avec scrypt (sel aléatoire), 10 caractères minimum. Blocage d'une minute après 5 échecs.
- **Sessions** dans un cookie signé (HMAC-SHA256) avec les attributs `HttpOnly`, `Secure` et `SameSite=Strict`, d'une durée de 12 h. Changer un mot de passe ou désactiver un compte ferme immédiatement ses sessions.
- **Contrôle d'accès côté serveur.** Un télévendeur ne peut ni voir la file d'un collègue, ni ouvrir le labo, ni enregistrer un compte-rendu au nom d'un autre.
- **En-têtes de sécurité** : CSP stricte (aucun script externe), `X-Frame-Options`, `nosniff`, `Referrer-Policy`. Les écritures n'acceptent que du JSON.
- **Conteneur** exécuté avec un utilisateur non root et un volume dédié aux données.
- **ERP en lecture seule** : le copilote n'écrit jamais dans l'ERP ni dans le datahub.

## Dépannage

| Symptôme | Piste |
|---|---|
| `SESSION_SECRET doit être défini` au démarrage | Compléter `.env` (étape 3) |
| Le certificat n'est pas délivré | Vérifier le DNS (`dig +short DOMAINE`) et l'ouverture du port 80 ; `docker compose logs caddy` |
| « Trop de tentatives » | Attendre une minute, ou réinitialiser le mot de passe (étape 5) |
| Un télévendeur voit une file vide | Son nom affiché ne correspond pas au champ « commercial » de l'ERP |
| Écran « Données » : « Lecture impossible » | `DATAHUB_URL` et `DATAHUB_TOKEN` dans `.env` ; depuis le serveur : `docker compose exec copilote python -m copilote.diagnostic` |
| Avec le simulateur, fiches incohérentes (stock périmé, rien en retard) | `DATAHUB_DATE_REFERENCE=2026-10-23` manquant : le jeu fictif est daté |
| Construction impossible derrière un proxy d'entreprise | `docker build --secret id=ca_entreprise,src=/chemin/ca.crt .` (voir l'en-tête du `Dockerfile`) |
