# Copilote télévente

MVP d'un assistant pour les télévendeurs d'un distributeur alimentaire (frais et surgelé).
Avant un appel, le télévendeur choisit un client. Le copilote prépare alors une **fiche d'appel** en quelques secondes :

- **les habitudes du client** : fréquence et jours de commande, panier moyen, produits récurrents, tendance ;
- **les produits habituels pas encore commandés** sur la période en cours, avec une alerte quand un produit semble parti chez un concurrent ;
- **le stock à écouler** (DLC courte ou surstock) qui intéresse ce client, avec une remise suggérée ;
- **des suggestions** : produits adoptés par des établissements similaires et que ce client n'achète pas encore ;
- **2 ou 3 phrases d'accroche** prêtes à dire au téléphone.

> Toutes les données de ce dépôt sont **fictives**. Elles sont générées par un script, en attendant l'accès au datahub de l'ERP.

---

## Comment ça marche

```
┌─────────────┐   ┌──────────────────────┐   ┌───────────────────────┐   ┌──────────────┐
│ Page web    │──▶│ API FastAPI          │──▶│ Agent (Claude)        │──▶│ Outils métier│──▶ Datahub
│ (mobile)    │   │ /clients, /fiche     │   │ ou mode repli         │   │ déterministes│   (mock | http)
└─────────────┘   └──────────────────────┘   └───────────────────────┘   └──────────────┘
```

| Dossier | Rôle |
|---|---|
| `datahub/base.py` | Interface abstraite `DataSource` (lecture seule) et objets métier : client, produit, commande, lot |
| `datahub/mock.py` | Source simulée, lue depuis `datahub/donnees/mock_data.json` |
| `datahub/http.py` | Squelette du client REST pour le vrai datahub (voir plus bas) |
| `scripts/generer_donnees_mock.py` | Générateur seedé du jeu de données fictif |
| `agent/tools.py` | Les 4 outils métier : `historique_client`, `produits_habituels_manquants`, `stock_a_ecouler`, `suggestions_croisees` |
| `agent/agent.py` | Boucle de *tool use* avec Claude, avec bascule automatique en mode repli |
| `agent/fiche.py` | Structure de la fiche, assemblage et garde-fous, mode repli, rendu texte |
| `api/main.py`, `api/static/index.html` | API et page web |
| `tests/` | Tests pytest |

### Le partage des rôles entre l'IA et le code

Les **chiffres viennent du code, les mots viennent de l'IA**.

1. Les outils métier font tous les calculs : rythmes d'achat, retards, rotation du stock, remises. Ce code est classique, déterministe et testé.
2. Claude (`claude-sonnet-5-5`) appelle ces outils, puis rédige la fiche. Il choisit ce qui compte pour ce client, formule les arguments et écrit les accroches. Il rend sa rédaction en JSON structuré via l'outil `soumettre_fiche`.
3. La fiche finale est assemblée par le code, qui applique des **garde-fous** :
   - tout produit cité par l'IA mais absent des résultats des outils est écarté ;
   - une remise supérieure à la remise suggérée est ramenée à ce plafond ;
   - prix, DLC, quantités et indicateurs proviennent uniquement des outils.
4. La fiche est renvoyée en JSON structuré et en texte (à copier ou imprimer).

**Mode repli.** Sans clé `ANTHROPIC_API_KEY`, ou si l'IA est indisponible (réseau, quota, refus, réponse invalide), la fiche est rédigée par des gabarits à partir des mêmes outils. La démo fonctionne donc toujours. La fiche indique clairement son mode : « Rédigée par IA » ou « Mode repli ».

### Règles métier (dans `agent/tools.py`)

| Règle | Valeur |
|---|---|
| Période analysée | 6 derniers mois |
| Produit « habituel » | Présent dans au moins 30 % des commandes et commandé au moins 3 fois |
| Produit « manquant » | Pas commandé depuis plus de 1,5 fois son rythme habituel (minimum 7 jours). La « période en cours » est donc propre à chaque produit et à chaque client. |
| Produit « décroché » | Pas commandé depuis plus de 3 fois son rythme habituel : probable achat chez un concurrent |
| DLC courte | Frais : 30 % de la durée de vie, entre 2 et 5 jours. Surgelé : 30 jours. Un lot qui expire le jour même est exclu (il ne peut plus être livré). |
| Surstock | Plus de 14 jours de ventes en stock pour le frais, plus de 90 jours pour le surgelé (rotation calculée sur 4 semaines) |
| Remise suggérée | DLC courte frais : 30 % à J+1, 25 % à J+2, 20 % à J+3, 15 % au-delà. Surgelé à DLC proche : 15 à 20 %. Surstock : 10 à 15 %. **Plafond : 30 %.** |
| Tendance | Chiffre d'affaires moyen par semaine d'activité, 12 dernières semaines comparées aux 12 précédentes. Les fermetures, comme les vacances scolaires, ne faussent donc pas le calcul. |
| Pertinence du stock pour un client | Produit acheté régulièrement > déjà acheté > acheté par au moins 2 clients du même type |

Tous ces seuils sont des constantes regroupées en tête de `agent/tools.py`, faciles à ajuster avec les équipes commerciales.

---

## Lancement

Prérequis : Python 3.12 ou plus.

```bash
python -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt

# Démarrer l'application (mode repli si aucune clé n'est définie)
uvicorn api.main:app --reload
# puis ouvrir http://localhost:8000
```

Pour activer l'IA :

```bash
export ANTHROPIC_API_KEY=sk-ant-...
# facultatif : export ANTHROPIC_MODEL=claude-sonnet-5-5
uvicorn api.main:app --reload
```

### Endpoints

| Méthode | Chemin | Description |
|---|---|---|
| GET | `/` | Page web : liste des clients, puis fiche d'appel |
| GET | `/clients` | Liste des clients (JSON) |
| GET | `/clients/{id}/fiche` | Fiche d'appel (JSON, avec sa version `texte`). Elle est mise en cache pour la journée ; `?regenerer=true` force une nouvelle génération. |
| GET | `/sante` | Source de données active, date de référence, mode IA ou repli |
| GET | `/docs` | Documentation interactive de l'API (générée par FastAPI) |

### Variables d'environnement

| Variable | Défaut | Rôle |
|---|---|---|
| `DATASOURCE` | `mock` | `mock` (données simulées) ou `http` (vrai datahub) |
| `ANTHROPIC_API_KEY` | (vide) | Clé d'API Anthropic. Si elle est absente, l'application tourne en mode repli. |
| `ANTHROPIC_MODEL` | `claude-sonnet-5-5` | Modèle Claude utilisé |
| `MOCK_DATA_PATH` | `datahub/donnees/mock_data.json` | Autre fichier de données simulées |
| `DATAHUB_URL`, `DATAHUB_TOKEN`, `DATAHUB_TIMEOUT` | (vides), 10 s | Accès au vrai datahub |

Un modèle de configuration est fourni dans `.env.example`.

### Tests

```bash
pytest
```

Les tests couvrent les outils métier sur des cas construits à la main, le jeu de données simulé, le client HTTP (avec un transport simulé, sans réseau), l'agent (avec un Claude simulé : boucle d'outils, relance, erreurs, bascule en repli) et l'API. Ils n'appellent jamais l'API Anthropic.

### Données simulées

```bash
python scripts/generer_donnees_mock.py   # régénère datahub/donnees/mock_data.json (graine fixe)
```

Le jeu de données contient 30 clients répartis en 9 types (restaurants, brasseries, pizzerias, cantines scolaires, EHPAD, boulangeries, traiteurs, hôtels, snacks), 80 produits (45 frais, 35 surgelés), environ 1 300 commandes sur 6 mois et environ 140 lots avec DLC.

Les habitudes sont construites pour être cohérentes : jours de commande fixes, produits typiques de chaque métier, saisonnalité (glaces l'été, cantines fermées en juillet-août), et des produits « décrochés » chez certains clients. Le stock contient des lots à DLC courte et des surstocks.

La date de référence (« aujourd'hui ») est figée au **23/10/2026** pour que la démo soit reproductible. Un test vérifie que le fichier versionné correspond exactement à la sortie du générateur.

---

## Brancher le vrai datahub

Le copilote ne dépend que de l'interface `DataSource` (`datahub/base.py`). Brancher le datahub ne demande **aucune modification** des outils, de l'agent ou de l'API. Il suffit de compléter `datahub/http.py`, où chaque point à confirmer est marqué `TODO(datahub)`.

### 1. Ce que le datahub doit fournir (lecture seule)

| Méthode `DataSource` | Appel supposé dans `http.py` | Données attendues |
|---|---|---|
| `get_clients()` | `GET /clients` | id, nom, type d'établissement, ville, contact, téléphone, commercial |
| `get_client(id)` | `GET /clients/{id}` | idem, pour un client ; 404 si inconnu |
| `get_order_history(client_id, depuis)` | `GET /commandes?client_id=…&depuis=AAAA-MM-JJ` | commandes **avec leurs lignes** : produit, quantité, prix unitaire HT |
| `get_products()` | `GET /produits` | code, libellé, catégorie, famille (frais/surgelé), unité, prix HT, durée de vie |
| `get_stock()` | `GET /stock/lots` | lots disponibles : produit, quantité, DLC, date de réception, entrepôt |

### 2. Points à implémenter ou à valider avec l'équipe du datahub

1. **Authentification** (`HttpDataSource.__init__`) : le code envoie aujourd'hui `Authorization: Bearer $DATAHUB_TOKEN`. À adapter si le datahub utilise une clé d'API dans un autre en-tête, un certificat client, etc.
2. **Chemins et paramètres** des cinq appels ci-dessus.
3. **Pagination** (`_get_liste`) : deux formats sont gérés, une liste JSON directe ou `{"items": [...], "next": url}`. À adapter au format réel (offset/limit, curseur…).
4. **Correspondance des champs** (fonctions `_vers_client`, `_vers_produit`, `_vers_commande`, `_vers_lot`) : renommer les champs ERP vers les objets métier, et traduire les codes ERP en libellés lisibles (type d'établissement, famille de produit). Quelques choix sont à arbitrer :
   - date de commande ou date de livraison pour l'historique ;
   - prix tarif ou prix net client ;
   - DLC ou DDM selon les produits ;
   - stock disponible uniquement, hors réservé et hors bloqué qualité.
5. **Lignes de commande** : si `/commandes` ne renvoie pas les lignes, ajouter un appel par commande, ou mieux, demander un endpoint qui les inclut.
6. **Volumétrie et performance** : `stock_a_ecouler` et `suggestions_croisees` lisent l'historique de tous les clients sur 4 semaines à 6 mois. Sur de gros volumes, mettre en cache le catalogue et ces historiques (par exemple pendant une heure), ou demander au datahub des agrégats déjà calculés : ventes par produit et par jour, produits achetés par type de client.
7. **Date de référence** : la source HTTP utilise la date du jour, alors que le mock utilise sa date figée. Rien à faire.

### 3. Mise en service et vérification

```bash
export DATASOURCE=http
export DATAHUB_URL=https://datahub.mon-entreprise.local/api/v1
export DATAHUB_TOKEN=...
uvicorn api.main:app
curl localhost:8000/sante          # doit afficher "source_donnees": "http"
curl localhost:8000/clients        # doit lister les vrais clients
```

Les tests de `tests/test_http.py` montrent comment valider la correspondance des champs sans réseau, avec `httpx.MockTransport`. Pour chaque endpoint réel, il est conseillé d'y ajouter un exemple de réponse anonymisé.

### Règle absolue : lecture seule

Le copilote **n'écrit jamais** dans le datahub ni dans l'ERP. L'interface `DataSource` ne contient que des méthodes de lecture, et `HttpDataSource._get` est le seul point d'accès au réseau (requêtes `GET` uniquement). Un test vérifie que seules des requêtes `GET` sont émises et qu'aucune méthode d'écriture n'existe. Si un jour le copilote doit préparer une commande, il devra la **proposer** au télévendeur, qui la saisira dans l'ERP comme aujourd'hui.

---

## Notes techniques sur l'IA

- **Modèle** : `claude-sonnet-5-5`, avec un effort `medium`, bon compromis entre qualité et latence pour enchaîner des outils.
- **Outils** déclarés avec `strict: true`, pour que les arguments respectent toujours le schéma.
- **Bascule serveur en cas de refus** (`fallbacks: "default"`, bêta `server-side-fallback-2026-07-01`) : si le modèle décline une requête, l'API la rejoue automatiquement sur un autre modèle. Pour la désactiver, retirer ces deux paramètres dans `agent/agent.py`.
- **Garde-fous de la boucle** : 6 allers-retours au maximum, une relance si Claude répond sans soumettre la fiche, et les erreurs d'outils sont renvoyées à Claude au lieu de faire planter la génération.
- **Coût** : une fiche représente quelques milliers de jetons en entrée (les résultats des outils). Le cache de l'API évite de régénérer une fiche déjà consultée dans la journée.

## Pistes après le MVP

- Branchement du datahub réel et calibrage des seuils avec les télévendeurs.
- Remontée du résultat de l'appel (produits acceptés ou refusés) pour mesurer l'efficacité des suggestions.
- File d'appels du jour triée par priorité : clients en retard, décrochages, stock à écouler.
- Authentification des utilisateurs et filtrage des clients par télévendeur.
