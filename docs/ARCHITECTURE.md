# Architecture du copilote télévente

Ce document décrit l'organisation du code, les choix de conception et le parcours d'une requête. Il sert à faciliter la relecture, le débogage et les évolutions.

## Principes

1. **Couches à dépendances descendantes.** Une couche n'importe que les couches inférieures :
   `domaine` ← `datahub`, `journal` ← `analyses` ← `fiche` ← `agent` ← `services` ← `application` ← `api`.
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
| Modifier les consignes données à l'IA | `copilote/agent/prompts.py` |
| Ajouter un outil pour l'IA | `copilote/agent/outils.py` (+ une analyse dans `copilote/analyses/`) |
| Ajouter un garde-fou | `copilote/fiche/assemblage.py` |
| Brancher le datahub | `copilote/datahub/http.py` (voir le README) |
| Ajouter un écran | `frontend/src/vues/`, puis le routeur dans `frontend/src/main.ts` |
| Ajouter un endpoint | `copilote/api/routes/`, puis `python -m scripts.generer_types_ts` |
