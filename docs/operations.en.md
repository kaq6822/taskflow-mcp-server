# Operations

Everything an operator needs to know: run modes, network binding, production release, environment variables, and DB/storage management.

## Run Modes

Choose one of three modes. **Production deployments use B or C.**

### A. Local Development (hot-reload)

```sh
make dev
```

Three processes start simultaneously:

| Process | Port | Role |
|---|---|---|
| Backend | `http://localhost:8000` | REST API · SSE |
| MCP Server | `http://localhost:7391/mcp` | MCP endpoint (Bearer auth) |
| Frontend | `http://localhost:5173` | React UI (API proxied via Vite) |

### B. Production (foreground)

```sh
make setup        # once
make build        # generate frontend/dist
make start        # backend serves SPA+API (:8000), mcp (:7391) separate
```

Access at `http://localhost:8000` (no Vite needed; same-origin so no CORS issues). Stop with `Ctrl+C`.

### C. Production (background, persists after logout)

```sh
make setup
make build
make start-bg     # nohup-based. creates logs/{backend,mcp}.pid + logs/taskflow.log
make logs         # tail -f logs/taskflow.log
make status       # running status · pid · port
make stop         # stop (pidfile + pkill fallback)
```

Change ports/binding with `make start-bg API_PORT=80 MCP_PORT=7391`.

## Common Commands

| Situation | Command | Notes |
|---|---|---|
| Initial install | `make setup` | venv · npm · migrate |
| Local dev | `make dev` | Vite binds to `localhost` only |
| LAN dev | `make dev-lan` | Vite · API · MCP all bind `0.0.0.0` |
| Production build | `make build` | generates `frontend/dist` |
| Production run | `make start` | backend serves SPA+API, MCP separate |
| Tests | `make test` | pytest |
| Reset DB | `make reset` | delete SQLite + storage, then migrate |
| Full clean | `make clean` | venv / node_modules / DB |

Individual services:

```sh
make dev-backend   # uvicorn app.main:app :8000 (dev)
make dev-mcp       # python -m app.mcp_server :7391 (dev)
make dev-frontend  # vite :5173 (dev)
make start-backend # production: SPA+API integrated
make start-mcp     # production MCP
```

## Network Binding

Default `make dev` binds Vite to `localhost` so it is only accessible from the **developer's local machine**. To access from a remote host (another device on the same LAN):

```sh
# 1) Run with LAN binding
make dev-lan TASKFLOW_CORS_ORIGINS=http://192.168.1.10:5173

# 2) Or fine-grained control with env vars
TASKFLOW_FRONTEND_HOST=0.0.0.0 \
TASKFLOW_API_HOST=0.0.0.0 \
TASKFLOW_MCP_HOST=0.0.0.0 \
TASKFLOW_API_HOST_PUBLIC=192.168.1.10 \
TASKFLOW_CORS_ORIGINS=http://192.168.1.10:5173 \
  make dev
```

- `TASKFLOW_FRONTEND_HOST` — Vite binding interface
- `TASKFLOW_API_HOST` / `TASKFLOW_MCP_HOST` — FastAPI / MCP binding interface
- `TASKFLOW_API_HOST_PUBLIC` — Host used by browser/external clients to reach the API (for Vite proxy target configuration)
- `TASKFLOW_CORS_ORIGINS` — **Comma-separated** origin whitelist. Must include the remote browser's origin when it calls `/api` directly. Vite-proxied calls are same-origin and are not affected. Use a single `*` in dev for allow-all.

> ⚠️ There is currently no login gate in the UI. Exposing with `dev-lan` allows anyone to create/run jobs — use only on trusted networks.

## Production Release

`make start` does the following:

1. Backend (uvicorn) serves **API + built SPA** from a single port — no separate Vite process, CORS issues naturally eliminated (same-origin).
2. MCP server runs independently on port 7391 as before.
3. Sets `TASKFLOW_ENV=production` so CORS is locked to items listed in `TASKFLOW_CORS_ORIGINS` (`*` is automatically removed in production for safety).

Example release pipeline:

```sh
# 1) Build
make build                       # generate frontend/dist

# 2) Configure environment (.env example)
# TASKFLOW_ENV=production
# TASKFLOW_API_PORT=80
# TASKFLOW_MCP_PORT=7391
# TASKFLOW_CORS_ORIGINS=https://taskflow.example.com
# TASKFLOW_FRONTEND_DIST_DIR=../frontend/dist

# 3) Run (wrap in systemd / pm2 / Docker as needed)
make start API_PORT=80

# Or manually
TASKFLOW_ENV=production \
TASKFLOW_FRONTEND_DIST_DIR=../frontend/dist \
  ./backend/.venv/bin/uvicorn app.main:app --host 0.0.0.0 --port 80

TASKFLOW_ENV=production \
  ./backend/.venv/bin/python -m app.mcp_server
```

When using a reverse proxy (Nginx/Caddy), proxy `/` and `/api/*` to the backend port, and `/mcp` to the MCP port. HTTPS termination is recommended at the reverse proxy layer.

## Environment Variable Reference

| Variable | Default | Description |
|---|---|---|
| `TASKFLOW_ENV` | `dev` | `dev` \| `production` |
| `TASKFLOW_DB_URL` | `sqlite+aiosqlite:///./taskflow.db` | DB URL |
| `TASKFLOW_STORAGE_DIR` | `./storage` | Artifact/log root |
| `TASKFLOW_STEP_CWD` | `./storage/runtime` | Step subprocess cwd |
| `TASKFLOW_API_HOST` / `TASKFLOW_API_PORT` | `0.0.0.0` / `8000` | Backend binding |
| `TASKFLOW_MCP_HOST` / `TASKFLOW_MCP_PORT` | `0.0.0.0` / `7391` | MCP binding |
| `TASKFLOW_MCP_MAX_SYNC_SEC` | `600` | Max wait for `run_job(sync)` |
| `TASKFLOW_FRONTEND_HOST` / `TASKFLOW_FRONTEND_PORT` | `localhost` / `5173` | Vite binding |
| `TASKFLOW_API_HOST_PUBLIC` | `localhost` | External API host (Vite proxy target) |
| `TASKFLOW_CORS_ORIGINS` | `http://localhost:5173,http://127.0.0.1:5173` | Comma-separated origin whitelist |
| `TASKFLOW_FRONTEND_DIST_DIR` | *(unset)* | SPA dist path for production mode |

## Data Locations

| Path | Contents |
|---|---|
| `backend/taskflow.db` | SQLite DB (jobs, runs, audit, keys) |
| `backend/storage/runtime/` | Step subprocess cwd |
| `backend/storage/logs/<run_id>/<step_id>.log` | Step log files |
| `backend/storage/artifacts/` | Uploaded artifact binaries |
| `logs/taskflow.log`, `logs/*.pid` | `make start-bg` log / PID files |

All runtime data is gitignored. Full reset with `make reset`.
