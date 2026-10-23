# Contrat d'interface du datahub

Ce document s'adresse à l'équipe du datahub. Il décrit les données dont le copilote télévente a besoin et la forme attendue des réponses. La version formelle (OpenAPI 3) est dans [`contrat-datahub.json`](contrat-datahub.json) : elle s'ouvre dans Swagger Editor, Postman ou Insomnia.

Si une réponse réelle diffère de ce contrat (noms de champs, pagination, authentification), ce n'est pas bloquant : l'adaptation se fait à un seul endroit du copilote (`copilote/datahub/http.py`). Ce document sert à se mettre d'accord rapidement.

## Principes

| Sujet | Attendu |
|---|---|
| Accès | **Lecture seule** : uniquement des requêtes `GET`. Le copilote n'écrit jamais ni dans le datahub ni dans l'ERP. |
| Format | JSON (UTF-8), dates au format `AAAA-MM-JJ`, montants HT en euros (nombre décimal) |
| Authentification | En-tête `Authorization: Bearer <jeton>` ; un jeton dédié au copilote, en lecture seule |
| Pagination | Paramètres `page` (à partir de 1) et `taille` ; réponse `{"items": [...], "next": "/chemin?...&page=2"}`, avec `next` à `null` sur la dernière page. Une liste JSON simple, non paginée, est aussi acceptée. |
| Erreurs | `401` jeton absent ou invalide, `404` ressource inconnue, `5xx` incident |
| Performance visée | Moins de 2 s par ressource complète. Le copilote met les réponses en cache 5 minutes. |

## Ressources

| Ressource | Paramètres | Contenu |
|---|---|---|
| `GET /clients` | `page`, `taille` | Clients **actifs** |
| `GET /clients/{client_id}` | — | Un client ; `404` s'il n'existe pas |
| `GET /commandes` | `client_id`, `depuis` (date incluse), `page`, `taille` | Historique des commandes, **lignes comprises**. Le copilote lit environ 6 mois. |
| `GET /produits` | `page`, `taille` | Catalogue |
| `GET /stock/lots` | `page`, `taille` | Stock **disponible à la vente**, par lot |

### Client

| Champ | Type | Exemple | Remarque |
|---|---|---|---|
| `id` | texte | `C001` | Identifiant ERP, unique |
| `nom` | texte | `Le Bouchon des Canuts` | Raison sociale ou enseigne |
| `type` | texte | `Restaurant` | Type d'établissement (sert à comparer des clients similaires) |
| `ville` | texte | `Lyon 4e` | |
| `contact` | texte | `Mme Girard` | Interlocuteur habituel |
| `telephone` | texte | `04 78 91 24 13` | |
| `commercial` | texte | `Karim Bensaïd` | Télévendeur en charge. **Doit correspondre au nom affiché de son compte copilote** : c'est ce lien qui construit sa file d'appels. |

### Commande

| Champ | Type | Exemple | Remarque |
|---|---|---|---|
| `id` | texte | `CMD001303` | Unique |
| `client_id` | texte | `C015` | Doit exister dans `/clients` |
| `date` | date | `2026-10-22` | Date de commande (voir les questions ci-dessous) |
| `lignes` | liste | | **Obligatoire** : sans les lignes, aucune habitude d'achat ne peut être calculée |
| `lignes[].produit_code` | texte | `FR004` | Doit exister dans `/produits` |
| `lignes[].quantite` | nombre | `6` | Dans l'unité de vente du produit, strictement positive |
| `lignes[].prix_unitaire_ht` | nombre | `4.6` | Prix réellement facturé |

### Produit

| Champ | Type | Exemple | Remarque |
|---|---|---|---|
| `code` | texte | `FR004` | Unique |
| `libelle` | texte | `Crème liquide 35 % 1 L` | |
| `categorie` | texte | `Crèmerie` | |
| `famille` | `frais` ou `surgele` | `frais` | Détermine les règles de DLC courte et de remise |
| `unite` | texte | `brique` | Unité de vente : kg, colis, carton, bac… |
| `prix_unitaire_ht` | nombre | `4.6` | Prix tarif |
| `duree_vie_jours` | entier | `30` | Durée de vie typique entre réception et DLC (frais) |

### Lot de stock

| Champ | Type | Exemple | Remarque |
|---|---|---|---|
| `id` | texte | `L2610-0003` | Numéro de lot |
| `produit_code` | texte | `FR003` | Doit exister dans `/produits` |
| `quantite` | nombre | `22` | Quantité disponible, dans l'unité de vente |
| `dlc` | date | `2026-11-03` | Date limite de consommation |
| `date_reception` | date | `2026-10-09` | |
| `entrepot` | texte | `Entrepôt froid positif` | |

## Questions à trancher ensemble

1. **Date d'une commande** : date de saisie ou date de livraison ? Le copilote raisonne en « jour habituel de commande » ; la date de saisie est préférable.
2. **Prix d'une ligne** : prix net facturé (après remises client) ? Et pour le catalogue, prix tarif général ?
3. **DLC ou DDM** : pour les surgelés, la date fournie est-elle une DDM ? Le copilote les traite différemment du frais.
4. **Stock disponible** : hors stock réservé, en préparation ou bloqué qualité ? Les lots périmés doivent être exclus.
5. **Clients actifs** : quel critère (compte ouvert, commande depuis moins d'un an…) ?
6. **Télévendeur** : le champ `commercial` contient-il un nom, un code vendeur ou un identifiant ? Une table de correspondance est possible.
7. **Volumétrie** : nombre de clients, de commandes par mois et de lignes par commande, pour dimensionner la pagination.

## Vérifier un branchement

Le copilote fournit deux outils, utilisables dès la première connexion :

- **Le simulateur** (`python -m copilote.datahub.simulateur`) répond exactement selon ce contrat. Il sert de référence et peut injecter des anomalies (`--anomalies`).
- **Le diagnostic** (`python -m copilote.diagnostic`, ou l'écran « Données » pour les responsables) interroge la source réelle et produit un rapport :
  - temps de réponse et volume de chaque ressource ;
  - respect du contrat : lecture d'un client par son identifiant, `404` sur un client inconnu, filtres `client_id` et `depuis`, présence des lignes de commande ;
  - qualité des données : 15 règles (doublons, références orphelines, prix à 0 €, durées de vie manquantes, lots périmés ou reçus après leur DLC, quantités anormales, clients sans télévendeur…), avec pour chacune les identifiants ERP à corriger.

Code de sortie du diagnostic : `0` conforme (ou simples alertes), `1` corrections nécessaires, `2` lecture impossible (datahub injoignable, jeton refusé, réponse non conforme au contrat…). Il peut donc servir de contrôle automatique après chaque évolution du datahub.
