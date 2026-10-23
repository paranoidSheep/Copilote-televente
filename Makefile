# Raccourcis de développement. `make aide` liste les cibles.
PYTHON ?= python3

.PHONY: aide installer lancer demo tests qualite types front donnees cassettes verifier

aide:  ## Liste les cibles
	@grep -E '^[a-z]+:.*##' $(MAKEFILE_LIST) | awk -F':.*## ' '{printf "  %-12s %s\n", $$1, $$2}'

installer:  ## Installe les dépendances Python
	$(PYTHON) -m pip install -r requirements-dev.txt

lancer:  ## Lance le serveur sur http://localhost:8000
	$(PYTHON) -m copilote --reload

demo:  ## Remplit le journal avec des appels fictifs (démonstration)
	$(PYTHON) -m scripts.peupler_journal_demo --vider

tests:  ## Tests avec couverture
	$(PYTHON) -m pytest --cov --cov-report=term-missing:skip-covered

qualite:  ## Lint, formatage et typage strict
	ruff check . && ruff format --check . && $(PYTHON) -m mypy

types:  ## Régénère les types TypeScript à partir de l'API
	$(PYTHON) -m scripts.generer_types_ts

front: types  ## Compile le frontend TypeScript
	cd frontend && npx tsc -p tsconfig.json

donnees:  ## Régénère le jeu de données fictif
	$(PYTHON) -m scripts.generer_donnees_mock

cassettes:  ## Vérifie les rédactions de l'IA simulée
	$(PYTHON) -m scripts.cassettes verifier

verifier: qualite tests cassettes  ## Tout ce que vérifie la CI côté Python
	$(PYTHON) -m scripts.generer_types_ts --verifier
