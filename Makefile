.DEFAULT_GOAL := help
SHELL := /bin/bash

help: ## Show this help
	@grep -E '^[a-zA-Z_-]+:.*?## .*$$' $(MAKEFILE_LIST) | awk 'BEGIN {FS = ":.*?## "}; {printf "  \033[36m%-18s\033[0m %s\n", $$1, $$2}'

install: ## Install dev dependencies
	pip install -r requirements/dev.txt

env: ## Create .env from the example
	@test -f .env || cp .env.example .env && echo ".env ready"

up: env ## Start the full stack
	docker compose up -d --build

down: ## Stop the stack
	docker compose down

logs: ## Tail backend logs
	docker compose logs -f backend

ps: ## Show container status
	docker compose ps

migrate: ## Apply migrations inside the backend container
	docker compose exec backend alembic upgrade head

revision: ## Autogenerate a migration: make revision m="add orders"
	docker compose exec backend alembic revision --autogenerate -m "$(m)"

downgrade: ## Roll back one migration
	docker compose exec backend alembic downgrade -1

superuser: ## Create/ensure the bootstrap superuser
	docker compose exec backend python scripts/create_superuser.py

shell: ## Open a shell in the backend container
	docker compose exec backend bash

test: ## Run the unit/API suite
	pytest

test-cov: ## Run tests with coverage
	pytest --cov=backend/app --cov-report=term-missing --cov-report=xml

lint: ## Ruff check + format check
	ruff check backend tests dashboard
	ruff format --check backend tests dashboard

format: ## Auto-format
	ruff check --fix backend tests dashboard
	ruff format backend tests dashboard

typecheck: ## Static types
	mypy backend/app

check: lint typecheck test ## Everything CI runs

clean: ## Remove caches
	find . -type d -name __pycache__ -exec rm -rf {} + 2>/dev/null || true
	rm -rf .pytest_cache .mypy_cache .ruff_cache htmlcov .coverage coverage.xml

.PHONY: help install env up down logs ps migrate revision downgrade superuser shell test test-cov lint format typecheck check clean
