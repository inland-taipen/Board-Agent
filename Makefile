# BoardLens AI - developer entry points.
.DEFAULT_GOAL := help
SHELL := /bin/bash
PY := backend/.venv/bin/python

.PHONY: help setup backend frontend dev test lint sample brief build up down clean

help: ## Show this help
	@grep -hE '^[a-zA-Z_-]+:.*?## ' $(MAKEFILE_LIST) \
		| awk 'BEGIN{FS=":.*?## "}{printf "  \033[36m%-12s\033[0m %s\n", $$1, $$2}'

setup: ## Create the venv, install the backend and the frontend
	cd backend && uv venv --python 3.12 .venv && uv pip install -e ".[dev]"
	cd frontend && npm install
	@test -f .env || (cp .env.example .env && echo "Created .env - add your ANTHROPIC_API_KEY")

backend: ## Run the API on :8000
	cd backend && .venv/bin/uvicorn boardlens.main:app --reload --port 8000

frontend: ## Run the web interface on :5173
	cd frontend && npm run dev

dev: ## Run both (needs two terminals; this starts the API and tells you the rest)
	@echo "Run 'make backend' in one terminal and 'make frontend' in another."
	@echo "Then open http://localhost:5173"

test: ## Run the backend test suite and the frontend typecheck
	cd backend && .venv/bin/python -m pytest -q
	cd frontend && npx tsc --noEmit

lint: ## Lint the backend
	cd backend && .venv/bin/ruff check boardlens tests scripts

sample: ## Generate a synthetic board pack in ./sample_pack
	cd backend && .venv/bin/python scripts/make_sample_pack.py ../sample_pack

brief: sample ## Generate a briefing from ./sample_pack (needs ANTHROPIC_API_KEY)
	cd backend && .venv/bin/boardlens brief \
		--client "Meridian Industries Limited" \
		--meeting "119th Board Meeting" \
		--date 2026-08-21 \
		--dir ../sample_pack \
		--out ../out

build: ## Build the production image
	docker compose build

up: ## Run the production image on :8000
	docker compose up -d && echo "BoardLens on http://localhost:8000"

down: ## Stop it
	docker compose down

clean: ## Remove local state (destroys uploaded packs and briefings)
	rm -rf storage out sample_pack backend/.pytest_cache
