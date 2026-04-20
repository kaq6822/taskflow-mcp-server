.PHONY: setup setup-backend setup-frontend dev dev-backend dev-mcp dev-frontend test migrate reset clean

PY := python3
VENV := backend/.venv
PYBIN := $(VENV)/bin
PIP := $(PYBIN)/pip
UVICORN := $(PYBIN)/uvicorn
ALEMBIC := $(PYBIN)/alembic
PYTEST := $(PYBIN)/pytest

setup: setup-backend setup-frontend migrate
	@echo "\n✓ setup complete. run 'make dev' to start."

setup-backend:
	$(PY) -m venv $(VENV)
	$(PIP) install --upgrade pip
	$(PIP) install -e "backend[dev]"

setup-frontend:
	cd frontend && npm install

migrate:
	cd backend && ../$(ALEMBIC) upgrade head

dev:
	@echo "starting backend (8000) + mcp (7391) + frontend (5173)"
	@trap 'kill 0' INT TERM EXIT; \
	  $(MAKE) -j3 dev-backend dev-mcp dev-frontend

dev-backend:
	cd backend && ../$(UVICORN) app.main:app --host 0.0.0.0 --port 8000 --reload

dev-mcp:
	cd backend && ../$(PYBIN)/python -m app.mcp_server

dev-frontend:
	cd frontend && npm run dev

test:
	cd backend && ../$(PYTEST) -v

reset:
	rm -f backend/taskflow.db backend/taskflow.db-journal
	rm -rf backend/storage
	$(MAKE) migrate

clean:
	rm -rf $(VENV) frontend/node_modules frontend/dist
	rm -f backend/taskflow.db
	rm -rf backend/storage
