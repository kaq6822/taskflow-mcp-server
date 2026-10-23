.PHONY: setup setup-backend setup-frontend dev dev-backend dev-frontend \
        dev-lan build ensure-build start start-backend \
        start-bg stop status logs \
        test migrate reset clean

PY := python3
VENV := backend/.venv
PYBIN := $(VENV)/bin
PIP := $(PYBIN)/pip
ALEMBIC := $(PYBIN)/alembic
PYTEST := $(PYBIN)/pytest

# Runtime knobs — override on the command line or in .env
API_HOST       ?= 0.0.0.0
API_PORT       ?= 8000
MCP_HOST       ?= 0.0.0.0
MCP_PORT       ?= 7391
FRONTEND_HOST  ?= localhost
FRONTEND_PORT  ?= 5173

# Background bookkeeping — keeps pid + log files out of the app code
LOG_DIR        := logs
LOG_FILE       := $(LOG_DIR)/taskflow.log
BACKEND_PID    := $(LOG_DIR)/backend.pid

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
# Two processes: the backend (`python -m app` — REST API and MCP on their own
# ports, one Run Engine) and the Vite dev server. The frontend binds to
# FRONTEND_HOST (localhost by default); the API and MCP default to 0.0.0.0, so
# they ARE reachable from the network even here — pass API_HOST=127.0.0.1
# MCP_HOST=127.0.0.1 to keep them loopback-only.
# There is no auth on /api/*, so treat any non-loopback binding as public access
# to arbitrary command execution (see docs/security.md).
dev:
	@echo "dev → backend $(API_HOST):$(API_PORT) · mcp $(MCP_HOST):$(MCP_PORT) · frontend $(FRONTEND_HOST):$(FRONTEND_PORT)"
	@trap 'kill 0' INT TERM EXIT; \
	  $(MAKE) -j2 dev-backend dev-frontend

dev-backend:
	cd backend && TASKFLOW_API_HOST=$(API_HOST) TASKFLOW_API_PORT=$(API_PORT) \
	  TASKFLOW_MCP_HOST=$(MCP_HOST) TASKFLOW_MCP_PORT=$(MCP_PORT) \
	  ../$(PYBIN)/python -m app --reload

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
	@echo "\n✓ frontend built to frontend/dist — run 'make start' to launch"

# Ensures frontend/dist/index.html exists; builds on demand so `make start`
# "just works" the first time.
ensure-build:
	@if [ ! -f frontend/dist/index.html ]; then \
	  echo "frontend/dist/index.html not found — running 'make build' first"; \
	  $(MAKE) build; \
	fi

# ---- Production start ----------------------------------------------------
# One process: the built SPA and the JSON API on API_PORT, MCP on MCP_PORT.
# No Vite dev-server in this mode.
# Override with:
#   make start API_PORT=80 MCP_PORT=7391 TASKFLOW_CORS_ORIGINS=https://app.example.com
start: ensure-build
	@echo "start → production mode (SPA + API at :$(API_PORT), mcp :$(MCP_PORT))"
	$(MAKE) start-backend

start-backend:
	cd backend && TASKFLOW_ENV=production TASKFLOW_FRONTEND_DIST_DIR=../frontend/dist \
	  TASKFLOW_API_HOST=$(API_HOST) TASKFLOW_API_PORT=$(API_PORT) \
	  TASKFLOW_MCP_HOST=$(MCP_HOST) TASKFLOW_MCP_PORT=$(MCP_PORT) \
	  ../$(PYBIN)/python -m app

# ---- Background (production) --------------------------------------------
# Delegates to shell scripts under scripts/ so the logic stays readable and
# portable (Make recipes + `&` + `$!` compose poorly).
start-bg: ensure-build
	@API_HOST=$(API_HOST) API_PORT=$(API_PORT) MCP_HOST=$(MCP_HOST) MCP_PORT=$(MCP_PORT) \
	  LOG_DIR=$(LOG_DIR) LOG_FILE=$(LOG_FILE) BACKEND_PID_FILE=$(BACKEND_PID) \
	  bash scripts/start-bg.sh

stop:
	@LOG_DIR=$(LOG_DIR) BACKEND_PID_FILE=$(BACKEND_PID) \
	  bash scripts/stop.sh

status:
	@API_PORT=$(API_PORT) MCP_PORT=$(MCP_PORT) \
	  LOG_DIR=$(LOG_DIR) BACKEND_PID_FILE=$(BACKEND_PID) \
	  bash scripts/status.sh

logs:
	@if [ ! -f $(LOG_FILE) ]; then \
	  echo "no log at $(LOG_FILE). did you 'make start-bg'?"; exit 1; \
	fi
	@tail -f $(LOG_FILE)

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
	rm -rf $(LOG_DIR)
