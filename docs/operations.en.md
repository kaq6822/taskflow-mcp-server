# Operations

Everything an operator needs to know: run modes, network binding, production release, environment variables, and DB/storage management.

## Run Modes

Choose one of three modes. **Production deployments use B or C.**

### A. Local Development (hot-reload)

```sh
make dev
```

Two processes start simultaneously. One backend process (`python -m app --reload`, restarts on code changes) serves both the API and MCP:

| Process | Port | Role |
|---|---|---|
| Backend | `http://localhost:8000` | REST API · SSE |
| | `http://localhost:7391/mcp` | MCP endpoint (Bearer auth) — same process as the backend |
| Frontend | `http://localhost:5173` | React UI (API proxied via Vite) |

### B. Production (foreground)

```sh
make setup        # once
make build        # generate frontend/dist
make start        # one process: SPA+API (:8000) + MCP (:7391)
```

Access at `http://localhost:8000` (no Vite needed; same-origin so no CORS issues). Stop with `Ctrl+C`.

`make start` / `make start-bg` build automatically **only when `frontend/dist/index.html` is missing**. An existing `dist` is served as-is, so after moving to a version with frontend changes you must run `make build` yourself ([Upgrading](#upgrading)).

### C. Production (background, persists after logout)

```sh
make setup
make build
make start-bg     # nohup-based. creates logs/backend.pid + logs/taskflow.log
make logs         # tail -f logs/taskflow.log
make status       # running status · pid · port
make stop         # stop — SIGTERM, wait up to 20s (STOP_TIMEOUT_SEC), then SIGKILL. Running runs are recorded as `서버 재시작으로 중단`. Also stops the old two-process layout
```

Change ports/binding with `make start-bg API_PORT=80 MCP_PORT=7391`.

## Common Commands

| Situation | Command | Notes |
|---|---|---|
| Initial install | `make setup` | venv · npm · migrate |
| Local dev | `make dev` | Vite binds to `localhost` only |
| LAN dev | `make dev-lan` | Vite · API · MCP all bind `0.0.0.0` |
| Production build | `make build` | generates `frontend/dist` |
| Production run | `make start` | one process serves SPA+API and MCP |
| Tests | `make test` | pytest |
| DB migration | `make migrate` | `alembic upgrade head` — required after upgrading |
| Reset DB | `make reset` | delete SQLite + storage, then migrate |
| Full clean | `make clean` | venv / node_modules / DB |

Individual services:

```sh
make dev-backend   # python -m app --reload (API :8000 + MCP :7391, dev)
make dev-frontend  # vite :5173 (dev)
make start-backend # production: SPA+API+MCP in one process
```

## Network Binding

Default `make dev` binds Vite to `localhost`. The **backend and MCP default to `0.0.0.0`**, though, so they are reachable from the network even under `make dev` — for loopback only, use `make dev API_HOST=127.0.0.1 MCP_HOST=127.0.0.1`. To use the UI from a remote host (another device on the same LAN):

```sh
# 1) Run with LAN binding
make dev-lan TASKFLOW_CORS_ORIGINS=http://192.168.1.10:5173

# 2) Or fine-grained control with Make variables
make dev FRONTEND_HOST=0.0.0.0 API_HOST=0.0.0.0 MCP_HOST=0.0.0.0 \
  TASKFLOW_CORS_ORIGINS=http://192.168.1.10:5173
```

The make targets take bindings as **Make variables** (`API_HOST`/`API_PORT`/`MCP_HOST`/`MCP_PORT`/`FRONTEND_HOST`/`FRONTEND_PORT`) and hand them to each process. `TASKFLOW_*_HOST` / `TASKFLOW_*_PORT` from `.env` or the shell are overwritten by those values and have no effect there.

- `FRONTEND_HOST` — Vite binding interface (passed to Vite as `TASKFLOW_FRONTEND_HOST`)
- `API_HOST` / `MCP_HOST` — REST API (`TASKFLOW_API_HOST`) / MCP (`TASKFLOW_MCP_HOST`) binding interface. The ports are separate, so the unauthenticated `/api/*` can be bound to `127.0.0.1` while only MCP is exposed
- `TASKFLOW_API_HOST_PUBLIC` — Vite proxy target host. `make dev-frontend` sets it to the `API_HOST` value
- `TASKFLOW_CORS_ORIGINS` — **Comma-separated** origin whitelist. Must include the remote browser's origin when it calls `/api` directly. Vite-proxied calls are same-origin and are not affected. Use a single `*` in dev for allow-all.

> ⚠️ There is currently no login gate in the UI. Exposing with `dev-lan` allows anyone to create/run jobs — and, since there is no restriction on what a step's `cmd` may run (see [Security](./security.en.md)), that means arbitrary commands on the server. Use only on trusted networks.

## Production Release

`make start` does the following:

1. Backend serves **API + built SPA** from a single port — no separate Vite process, CORS issues naturally eliminated (same-origin).
2. MCP is served by the same process on its own port, 7391 (it starts accepting requests only after the API startup has finished).
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
cd backend && TASKFLOW_ENV=production \
TASKFLOW_FRONTEND_DIST_DIR=../frontend/dist \
TASKFLOW_API_PORT=80 \
  .venv/bin/python -m app
```

When using a reverse proxy (Nginx/Caddy), proxy `/` and `/api/*` to the backend port, and `/mcp` to the MCP port. HTTPS termination is recommended at the reverse proxy layer.

The API and MCP run in one process (`python -m app`) sharing one Run Engine. If either fails to start (port in use, etc.) or the process receives a stop signal, both go down, and stopping the process stops all runs in progress. A cut-off run is finalized as `FAILED` (`서버 재시작으로 중단`) when the process starts again. A job allows only one `RUNNING` run, so the job cannot run again until the restart — if you cannot wait, clean it up with `POST /api/runs/{id}/cancel` or the stop button in the UI. Runs started before `0005_single_running_run` are also cleaned up at startup.

## Upgrading

After updating the code to a new version, do the following in order:

```sh
git pull
make setup-backend   # if dependencies changed
make migrate         # update the DB schema (alembic upgrade head)
make build           # if the frontend changed — start/start-bg do not rebuild an existing dist
make stop && make start-bg   # or make start
```

- **The process layout changed.** The backend and the MCP server used to be separate processes; now it is the single `python -m app`. When upgrading across this change, run `make stop` before `make start-bg` so the old two processes are gone (`make stop` also handles the old pid layout). Leftovers would make the new process fail to start on the port conflict.
- **`make migrate` is required.** The table auto-creation at server start only creates missing tables; it does not add columns to existing ones. For example, run params (`0003_run_params` — `jobs.params`, `runs.params`) and run outputs (`0004_run_outputs` — `runs.outputs`) fail with `no such column` without the migration.
- Migrations live in `backend/alembic/versions/` and are applied to the DB that `TASKFLOW_DB_URL` points at. Back up `backend/taskflow.db` first.
- `make dev` serves the sources through Vite, so it needs no `make build`.

## Environment Variable Reference

`TASKFLOW_*_HOST` / `TASKFLOW_*_PORT` are what a manually launched `python -m app` reads. The make targets overwrite them with Make variables, as described in [Network Binding](#network-binding).

| Variable | Default | Description |
|---|---|---|
| `TASKFLOW_ENV` | `dev` | `dev` \| `production` |
| `TASKFLOW_DB_URL` | `sqlite+aiosqlite:///./taskflow.db` | DB URL |
| `TASKFLOW_STORAGE_DIR` | `./storage` | Artifact/log root |
| `TASKFLOW_STEP_CWD` | `./storage/runtime` | Default subprocess cwd when a step does not set `cwd` |
| `TASKFLOW_API_HOST` / `TASKFLOW_API_PORT` | `0.0.0.0` / `8000` | REST API binding (read by `python -m app`; make passes `API_HOST`/`API_PORT`). `TASKFLOW_API_PORT` is used as the Vite proxy target port. **Defaults to every interface, and `/api/*` has no auth** — set `API_HOST=127.0.0.1` to keep it loopback-only |
| `TASKFLOW_MCP_HOST` / `TASKFLOW_MCP_PORT` | `0.0.0.0` / `7391` | MCP binding (read by `python -m app`) |
| `TASKFLOW_MCP_MAX_SYNC_SEC` | `600` | Max wait for `run_job(sync)` |
| `TASKFLOW_FRONTEND_HOST` / `TASKFLOW_FRONTEND_PORT` | `localhost` / `5173` | Vite binding |
| `TASKFLOW_API_HOST_PUBLIC` | `localhost` | External API host (Vite proxy target) |
| `TASKFLOW_CORS_ORIGINS` | `http://localhost:5173,http://127.0.0.1:5173` | Comma-separated origin whitelist |
| `TASKFLOW_FRONTEND_DIST_DIR` | *(unset)* | SPA dist path for production mode |

## Step cwd Management

Steps run from `TASKFLOW_STEP_CWD` by default. For deployment jobs that need a specific execution directory, set step-level `cwd` in the Builder or REST job definition.

```json
{
  "id": "deploy",
  "cwd": "/opt/taskflow/apps/api",
  "cmd": ["./deploy.sh"],
  "timeout": 300
}
```

An explicit `cwd` must already exist and must be a directory. If it is missing or points to a file, the step ends as `FAILED`. For production deployment jobs, absolute paths are recommended over relative paths.

Using `cd /path` as a separate step is not supported. `cd` is shell/process state that does not carry over to later steps, and TaskFlow rejects it as a `policy.violation`.

## Data Locations

| Path | Contents |
|---|---|
| `backend/taskflow.db` | SQLite DB (jobs, runs, audit, keys) |
| `backend/storage/runtime/` | Default Step subprocess cwd (`TASKFLOW_STEP_CWD` default) |
| `backend/storage/logs/<run_id>/<step_id>.log` | Step log files |
| `backend/storage/artifacts/` | Uploaded artifact binaries |
| `logs/taskflow.log`, `logs/backend.pid` | `make start-bg` log / PID files |

All runtime data is gitignored. Full reset with `make reset`.
