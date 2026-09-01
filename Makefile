.PHONY: help backend-install backend-dev frontend-install frontend-dev migrate test lint build db-up db-down compose-up compose-down

PYTHON ?= python
NPM ?= npm
COMPOSE_FILE := deployment/docker/compose.p0.3.yml

help:
	@echo "Drishti AI P0.1-P0.3 platform tasks"
	@echo "  backend-install   Install backend plus development dependencies"
	@echo "  backend-dev       Start FastAPI with local reload"
	@echo "  frontend-install  Install frontend dependencies"
	@echo "  frontend-dev      Start the Vite development server"
	@echo "  migrate           Apply database migrations"
	@echo "  test              Run backend and frontend tests"
	@echo "  lint              Run backend lint and frontend lint/typecheck"
	@echo "  build             Build the frontend"
	@echo "  compose-up        Build/start PostGIS, API, and UI"
	@echo "  compose-down      Stop containers without deleting database data"

backend-install:
	$(PYTHON) -m pip install -e "apps/backend[analytics,dev]"

backend-dev:
	$(PYTHON) -m uvicorn app.main:app --reload --app-dir apps/backend --no-access-log

frontend-install:
	$(NPM) --prefix apps/frontend install

frontend-dev:
	$(NPM) --prefix apps/frontend run dev

migrate:
	cd apps/backend && $(PYTHON) -m alembic upgrade head

test:
	$(PYTHON) -m pytest apps/backend/tests
	$(NPM) --prefix apps/frontend test

lint:
	$(PYTHON) -m ruff check apps/backend
	$(NPM) --prefix apps/frontend run lint
	$(NPM) --prefix apps/frontend run typecheck

build:
	$(NPM) --prefix apps/frontend run build

db-up:
	docker compose -f $(COMPOSE_FILE) up -d postgres

db-down:
	docker compose -f $(COMPOSE_FILE) stop postgres

compose-up:
	docker compose -f $(COMPOSE_FILE) up --build -d

compose-down:
	docker compose -f $(COMPOSE_FILE) down
