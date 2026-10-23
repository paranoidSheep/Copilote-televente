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
| `ANTHROPIC_API_KEY` | `sk-ant-…` | Facultatif : sans clé, l'IA simulée est utilisée |

> Le fichier `.env` contient des secrets : il ne doit jamais être versionné. Il est déjà exclu par `.gitignore`.

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
| `responsable` | Toutes les files, statistiques globales, labo IA, diagnostic des données |
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

## 8. Supervision et journaux

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
| Construction impossible derrière un proxy d'entreprise | `docker build --secret id=ca_entreprise,src=/chemin/ca.crt .` (voir l'en-tête du `Dockerfile`) |
