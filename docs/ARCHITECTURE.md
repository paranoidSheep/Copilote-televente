# Architecture du copilote télévente

Ce document décrit l'organisation du code, les choix de conception et le parcours d'une requête. Il sert à faciliter la relecture, le débogage et les évolutions.

## Principes

1. **Couches à dépendances descendantes.** Une couche n'importe que les couches inférieures :
   `domaine` ← `datahub`, `journal`, `comptes` ← `analyses` ← `diagnostic`, `fiche` ← `agent`, `evaluation` ← `services` ← `application` ← `api`.
2. **Les calculs sont purs.** Les analyses prennent un `Referentiel` (instantané immuable des données) et renvoient des résultats typés. Elles ne font aucun accès réseau ni aucune écriture. On les teste avec des données construites à la main.
3. **Un seul endroit pour assembler.** `copilote/application.py` choisit les implémentations concrètes : source, stockage, fournisseurs d'IA, horloge. Les tests y injectent les leurs, sans « monkeypatch ».
4. **Typage strict partout.**
   - Les modèles pydantic sont immuables (`frozen`) et refusent les champs inconnus (`extra="forbid"`).
   - Python passe `mypy --strict`.
   - Les types TypeScript sont générés à partir du schéma OpenAPI.
5. **Toutes les règles métier sont au même endroit.** Seuils, remises et pondérations sont dans `analyses/regles.py`, dans un objet immuable qu'on peut remplacer dans les tests.
6. **Les erreurs sont typées.** `ErreurCopilote` et ses sous-classes sont traduites en codes HTTP en un seul endroit (`api/app.py`). Une erreur d'outil est renvoyée au LLM, qui peut se corriger. Une erreur du LLM déclenche le repli sans IA.

## Parcours d'une fiche d'appel

```
GET /clients/C005/fiche
  └─ api/routes/clients.py        fiche_client()
     └─ services/fiches.py        ServiceFiches.generer(client, mode)
        ├─ cache (client, date, mode) ? → renvoi direct
        ├─ referentiel.obtenir()          instantané des données (rafraîchi toutes les N secondes)
        ├─ journal.lister(client)         appels précédents (refus, rappels)
        ├─ analyses.construire_contexte() habitudes, manquants, stock, suggestions, appels
        ├─ agent.RedacteurIA.rediger()
        │   ├─ fournisseur.ouvrir_session(prompt, outils, {client_id})
        │   ├─ tour 1 : le LLM appelle 5 outils  → BoiteAOutils.executer() (verrouillée sur le client)
        │   ├─ tour 2 : approfondissement éventuel (details_produit)
        │   └─ tour 3 : soumettre_fiche(rédaction) → validée par le modèle Redaction
        │   (chaque étape est chronométrée dans la TraceExecution)
        ├─ en cas d'ErreurRedaction → fiche.rediger_sans_ia() (repli) avec avertissement et trace
        └─ fiche.assembler_fiche()        garde-fous + panier + rendu texte
```

## Chargement des données et diagnostic

Les analyses ne voient jamais de données incohérentes : elles sont filtrées au chargement de l'instantané. Le diagnostic relit exactement les mêmes écarts, ce qui garantit que « ce qui est écarté » et « ce qui est signalé » ne divergent jamais.

```
Referentiel.charger(source)                     source = mock, ou http derrière SourceEnCache
  └─ analyses.filtrer_exploitables()            doublons, références orphelines, commandes futures,
                                                lots périmés → écartés, chacun tracé par un Ecart

GET /admin/diagnostic                           (ou python -m copilote.diagnostic)
  └─ services/diagnostic.py                     ServiceDiagnostic : la source SANS le cache
     └─ diagnostic.diagnostiquer()
        ├─ connexion.lire_source()              chaque ressource chronométrée ; une erreur → « lecture impossible »
        ├─ connexion.verifier_contrat()         lecture unitaire, 404, filtres client_id et depuis, lignes
        └─ qualite.controler_qualite()          15 règles ; les règles « écartées » relisent les Ecart
```

Le simulateur (`datahub/simulateur.py`) est l'implémentation de référence du contrat REST : son schéma OpenAPI est exporté dans `docs/contrat-datahub.json`, et les tests vérifient que `HttpDataSource` → réseau → simulateur restitue exactement les données du mock et produit les mêmes fiches.

## Banc d'évaluation

```
POST /labo/evaluations {redacteurs, clients}      (ou python -m scripts.evaluer)
  └─ services/evaluation.py ServiceEvaluation     une campagne à la fois, en arrière-plan, 4 fiches en parallèle
     ├─ ServiceFiches.produire(client, rédacteur)  hors cache : fiche + contexte d'analyse + durée
     ├─ evaluation.evaluer_fiche()                 fidélité (corrections typées), couverture (signaux), format
     ├─ evaluation.synthetiser()                   moyennes, défauts, latence p50/p95, jetons, coût estimé
     └─ DepotEvaluationsSQLite                     historique complet, avec l'empreinte du prompt
```

Les critères sont des fonctions pures, sans IA juge : un même lot de fiches donne toujours la même note.

## Fournisseurs de LLM

Le contrat se trouve dans `agent/llm/types.py` :

```python
class FournisseurLLM(Protocol):
    nom: str
    modele: str

    def ouvrir_session(self, systeme, outils, metadonnees) -> SessionLLM: ...


class SessionLLM(Protocol):
    def envoyer(self, message: str | Sequence[ResultatOutil]) -> ReponseLLM: ...
```

Chaque session conserve son propre historique. L'agent ne manipule que des types neutres (`AppelOutil`, `ResultatOutil`, `ReponseLLM`) et ne dépend d'aucun SDK.

- **`FournisseurClaude`** traduit ces types vers le SDK `anthropic` (`client.beta.messages.create`). Il renvoie à l'API le contenu complet de chaque réponse, comme elle l'exige, et traduit les erreurs HTTP en `ErreurFournisseurLLM` avec une raison lisible par le télévendeur.
- **`FournisseurSimule`** rejoue une cassette JSON : les tours d'outils puis la rédaction. Il vérifie que chaque appel d'outil a reçu son résultat, comme l'API réelle.

Pour ajouter un fournisseur, par exemple un modèle hébergé en interne, il suffit d'implémenter ces deux protocoles et de l'enregistrer dans `application.fournisseurs_par_defaut`.

## Données et état

| Donnée | Propriétaire | Stockage | Écriture par le copilote |
|---|---|---|---|
| Clients, produits, commandes, stock | ERP | Datahub (ou mock JSON) | **Jamais** |
| Comptes-rendus d'appels | Copilote | SQLite local (`var/journal.sqlite3`) | Oui, uniquement ici |
| Comptes utilisateurs | Copilote | SQLite local (`var/utilisateurs.sqlite3`) | Oui (administration) |
| Campagnes d'évaluation | Copilote | SQLite local (`var/evaluations.sqlite3`) et rapports `var/evaluations/` | Oui (labo, `scripts.evaluer`) |
| Fiches générées | Copilote | Cache mémoire par (client, jour, mode) | Invalidé à chaque compte-rendu du client |
| Instantané `Referentiel` | Copilote | Mémoire, durée `CACHE_SECONDES` | — |

## Frontend

- **TypeScript strict, sans framework ni bundler.** Le code est compilé par `tsc` en modules ES servis tels quels par FastAPI : rien à installer côté serveur.
- **`dom.ts`** construit le DOM sans `innerHTML`. Tout le texte passe par des nœuds texte, ce qui protège contre l'injection HTML.
- **`types-api.ts`** est généré, et **`api.ts`** est le client typé.
- **Les vues** se trouvent dans `vues/`. Le routage utilise le fragment d'URL (`#/clients/C005`).
- **Chaque navigation rend dans un conteneur neuf** : une vue lente qui termine après un changement de page n'écrase pas la page suivante.

## Où intervenir pour…

| Besoin | Fichier |
|---|---|
| Changer un seuil ou une remise | `copilote/analyses/regles.py` |
| Modifier les consignes données à l'IA | `copilote/agent/prompts.py`, puis `python -m scripts.evaluer --redacteurs anthropic` pour mesurer l'effet |
| Ajouter un critère d'évaluation | `copilote/evaluation/criteres.py` |
| Ajouter un outil pour l'IA | `copilote/agent/outils.py` (+ une analyse dans `copilote/analyses/`) |
| Ajouter un garde-fou | `copilote/fiche/assemblage.py` |
| Brancher le datahub | `copilote/datahub/http.py` (voir le README et `docs/CONTRAT-DATAHUB.md`) |
| Faire évoluer le contrat du datahub | `copilote/datahub/simulateur.py`, puis `python -m scripts.exporter_contrat_datahub` |
| Ajouter une règle de qualité des données | `copilote/diagnostic/qualite.py` (et `analyses/exploitabilite.py` si l'enregistrement doit être écarté) |
| Ajouter un écran | `frontend/src/vues/`, puis le routeur dans `frontend/src/main.ts` |
| Ajouter un endpoint | `copilote/api/routes/`, puis `python -m scripts.generer_types_ts` |
