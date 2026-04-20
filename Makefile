.PHONY: setup setup-backend setup-frontend dev dev-backend dev-mcp dev-frontend \
        dev-lan dev-lan-backend dev-lan-mcp dev-lan-frontend \
        build start start-backend start-mcp test migrate reset clean

PY := python3
VENV := backend/.venv
PYBIN := $(VENV)/bin
PIP := $(PYBIN)/pip
UVICORN := $(PYBIN)/uvicorn
ALEMBIC := $(PYBIN)/alembic
PYTEST := $(PYBIN)/pytest

# Runtime knobs — override on the command line or in .env
API_HOST       ?= 0.0.0.0
API_PORT       ?= 8000
MCP_HOST       ?= 0.0.0.0
MCP_PORT       ?= 7391
FRONTEND_HOST  ?= localhost
FRONTEND_PORT  ?= 5173

# ---- Setup ---------------------------------------------------------------
setup: setup-backend setup-frontend migrate
	@echo "\n✓ setup complete. run 'make dev' (loopback) or 'make dev-lan' (LAN)."

setup-backend:
	$(PY) -m venv $(VENV)
	$(PIP) install --upgrade pip
	$(PIP) install -e "backend[dev]"

setup-frontend:
	cd frontend && npm install

migrate:
	cd backend && ../$(ALEMBIC) upgrade head

# ---- Dev (loopback) ------------------------------------------------------
# Three processes, each bound to 127.0.0.1 unless FRONTEND_HOST/API_HOST is
# overridden. Intended for a single developer on localhost.
dev:
	@echo "dev → backend $(API_HOST):$(API_PORT) · mcp $(MCP_HOST):$(MCP_PORT) · frontend $(FRONTEND_HOST):$(FRONTEND_PORT)"
	@trap 'kill 0' INT TERM EXIT; \
	  $(MAKE) -j3 dev-backend dev-mcp dev-frontend

dev-backend:
	cd backend && ../$(UVICORN) app.main:app --host $(API_HOST) --port $(API_PORT) --reload

dev-mcp:
	cd backend && TASKFLOW_MCP_HOST=$(MCP_HOST) TASKFLOW_MCP_PORT=$(MCP_PORT) ../$(PYBIN)/python -m app.mcp_server

dev-frontend:
	cd frontend && TASKFLOW_FRONTEND_HOST=$(FRONTEND_HOST) TASKFLOW_FRONTEND_PORT=$(FRONTEND_PORT) \
	  TASKFLOW_API_HOST_PUBLIC=$(API_HOST) TASKFLOW_API_PORT=$(API_PORT) \
	  npm run dev

# ---- Dev (LAN) -----------------------------------------------------------
# Binds every service to 0.0.0.0 so remote hosts on the same network can
# reach the UI. CORS also needs to allow the remote origin; override via
# TASKFLOW_CORS_ORIGINS, e.g.:
#   make dev-lan TASKFLOW_CORS_ORIGINS=http://192.168.1.10:5173
dev-lan: FRONTEND_HOST=0.0.0.0
dev-lan:
	@echo "dev-lan → all services bound to 0.0.0.0"
	@echo "  Remember to set TASKFLOW_CORS_ORIGINS to your public origin."
	$(MAKE) dev FRONTEND_HOST=0.0.0.0

# ---- Production build ----------------------------------------------------
build:
	cd frontend && npm run build
	@echo "\n✓ frontend built to frontend/dist — set TASKFLOW_FRONTEND_DIST_DIR and run 'make start'"

# ---- Production start ----------------------------------------------------
# Backend serves the built SPA from frontend/dist and the JSON API from the
# same port; MCP runs on its own port. No Vite dev-server in this mode.
# Override with:
#   make start API_PORT=80 MCP_PORT=7391 TASKFLOW_CORS_ORIGINS=https://app.example.com
start:
	@echo "start → production mode (backend serves SPA + API, mcp separate)"
	@trap 'kill 0' INT TERM EXIT; \
	  $(MAKE) -j2 start-backend start-mcp

start-backend:
	cd backend && TASKFLOW_ENV=production TASKFLOW_FRONTEND_DIST_DIR=../frontend/dist \
	  ../$(UVICORN) app.main:app --host $(API_HOST) --port $(API_PORT) --workers 1

start-mcp:
	cd backend && TASKFLOW_ENV=production TASKFLOW_MCP_HOST=$(MCP_HOST) TASKFLOW_MCP_PORT=$(MCP_PORT) \
	  ../$(PYBIN)/python -m app.mcp_server

# ---- Ops ------------------------------------------------------------------
test:
	cd backend && ../$(PYTEST) -v

reset:
	rm -f backend/taskflow.db backend/taskflow.db-journal backend/taskflow.db-wal backend/taskflow.db-shm
	rm -rf backend/storage
	$(MAKE) migrate

clean:
	rm -rf $(VENV) frontend/node_modules frontend/dist
	rm -f backend/taskflow.db
	rm -rf backend/storage
