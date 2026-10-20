PYTHON := .venv/bin/python
COMPOSE := docker compose
.DEFAULT_GOAL := help

.PHONY: setup test schemas openapi up down local-up local-down local-status \
	seed demo-replay demo-cached demo-live evaluate reset-demo help

.PHONY: frontend-install frontend frontend-build

frontend-install:
	npm ci --prefix frontend

frontend:
	npm run dev --prefix frontend

frontend-build:
	npm run build --prefix frontend

help:
	@echo "Meridian targets"
	@echo "  make setup        create .venv, install locked deps, keys/tokens/.env"
	@echo "  make test         run the offline pytest suite"
	@echo "  make schemas      export OpenAPI documents to docs/openapi/"
	@echo "  make local-up     start the three services as local processes"
	@echo "  make local-down   stop the local process stack"
	@echo "  make up           build/start the Docker Compose stack"
	@echo "  make down         stop the Docker Compose stack"
	@echo "  make seed         ingest the baseline corpus (mode from .env)"
	@echo "  make demo-replay  reset + seed + all three demos in replay mode"
	@echo "  make demo-cached  reset + build synthetic cache + all three demos"
	@echo "  make demo-live    require credentials; live Slack extraction + demos"
	@echo "  make evaluate     run the labeled end-to-end evaluation"
	@echo "  make reset-demo   delete demo databases/sources (keeps keys and evidence)"
	@echo "  make frontend-install install the locked frontend dependencies"
	@echo "  make frontend     start the local findings workspace on :5173"
	@echo "  make frontend-build build the findings workspace for npm start"

setup:
	@test -x $(PYTHON) || python3.11 -m venv .venv
	$(PYTHON) -m pip install --upgrade pip
	$(PYTHON) -m pip install -r requirements.lock.txt
	$(PYTHON) scripts/setup.py

test:
	$(PYTHON) -m pytest

schemas: openapi
openapi:
	$(PYTHON) scripts/export_openapi.py

up: setup
	$(COMPOSE) up --build -d
	@echo "docker compose stack starting; readiness: curl http://127.0.0.1:8081/ready"

down:
	$(COMPOSE) down

local-up:
	$(PYTHON) scripts/stack.py up

local-down:
	$(PYTHON) scripts/stack.py down

local-status:
	$(PYTHON) scripts/stack.py status

seed:
	$(PYTHON) scripts/seed.py

demo-replay:
	$(PYTHON) scripts/run_demo.py --mode replay

demo-cached:
	$(PYTHON) scripts/run_demo.py --mode cached

demo-live:
	$(PYTHON) scripts/run_demo.py --mode live

evaluate:
	$(PYTHON) scripts/evaluate.py

reset-demo:
	$(PYTHON) scripts/reset_demo.py --yes
