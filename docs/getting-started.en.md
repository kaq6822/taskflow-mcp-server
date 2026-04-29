# Getting Started

A 5-minute guide to running TaskFlow for the first time and creating your first job from the UI.

## Requirements

- Python 3.11 or later (tested up to 3.14)
- Node.js 20+, npm 10+
- macOS · Linux (WSL recommended for Windows)

## Installation

```sh
git clone <this-repo> taskflow-mcp-server
cd taskflow-mcp-server
cp .env.example .env      # defaults are fine for most cases
make setup
```

What `make setup` does:

1. Creates a `backend/.venv` Python virtual environment
2. `pip install -e "backend[dev]"` — installs FastAPI, SQLAlchemy, `mcp` SDK, pytest, etc.
3. `cd frontend && npm install` — installs React and other frontend dependencies
4. `alembic upgrade head` — creates the `backend/taskflow.db` schema

Starts with an empty DB. No seed data is loaded.

## Running

```sh
make dev
```

Three processes start simultaneously:

| Process | Port | Role |
|---|---|---|
| Backend | `http://localhost:8000` | REST API · SSE |
| MCP Server | `http://localhost:7391/mcp` | MCP endpoint (Bearer auth) |
| Frontend | `http://localhost:5173` | React UI (API proxied via Vite) |

Open **http://localhost:5173** in your browser. On first run, the backend prints an admin session token to the console once (for future UI auth activation).

> Vite's default dev server binds to `localhost` only. For remote access or LAN sharing, see the network binding section in [Operations](./operations.en.md).

## Creating Your First Job

![Workflow Builder](./assets/03-builder.png)

1. Dashboard → `+ New Job`
2. In the Builder, fill in:
   - **ID**: `hello` (kebab-case, lowercase)
   - **Name**: `Hello Demo`
   - **Step 1**: argv = `["echo", "hello from taskflow"]`, timeout = 10
   - **Step 2**: argv = `["sleep", "1"]`, deps = `greet`, timeout = 5
3. `Save` → returns to Dashboard
4. Click `▷ Run` on the `hello` row
5. `LIVE` chip appears in the topbar → Monitor screen streams actual stdout via SSE
6. After completion, check the Audit screen for `job.create`, `job.run`, `job.run.done` events

## argv Allowlist

Step argv can only use commands registered in the local allowlist. The file is split in two so each environment can customise it without polluting the shared repo:

| Path | Tracked | Role |
|---|---|---|
| `backend/app/dev/allowlist.example.yaml` | in git | The shipped template shared across clones |
| `backend/app/dev/allowlist.yaml` | **`.gitignore`d** | The per-environment copy actually loaded at runtime |

`make setup` (or `make setup-backend`) copies the template into place on first install, and never overwrites an existing local copy. To regenerate manually, run `make bootstrap-allowlist`.

Defaults:

```yaml
allow:
  - ["echo"]
  - ["printf"]
  - ["sleep"]
  - ["ls"]
  - ["cat"]
  - ["/bin/true"]
  - ["/bin/false"]
  # + /bin/*, /usr/bin/* variants
```

Commands you need (e.g., `zip`, or the absolute path of an environment-specific wrapper script) must be added to **`allowlist.yaml`** — the local copy, not the template. Restart the backend after editing (`make stop && make start-bg`). In production, prefer pointing `TASKFLOW_ALLOWLIST_PATH` at an out-of-tree file (e.g., `/etc/taskflow/allowlist.yaml`) managed by your deployment tooling.

This is an intentional restriction to prevent accidents. See [Security](./security.en.md) for policy background.

## Step Working Directory (`cwd`)

Steps run from `TASKFLOW_STEP_CWD` (`./storage/runtime`) by default. Deployment jobs that need a specific directory should set step-level `cwd`.

```json
{
  "id": "deploy",
  "cwd": "/cms/cms_api",
  "cmd": ["./deploy.sh"],
  "timeout": 300,
  "deps": []
}
```

Using `cd /cms/cms_api` as a separate step is not supported. `cd` cannot change the working directory of later steps, so represent it with `cwd`.

## Output-Based Success / Failure Checks

The default success condition is still `exit_code == 0`. To additionally check stdout/stderr for specific text, set `success_contains` or `failure_contains` on the step.

```json
{
  "id": "health",
  "cmd": ["curl", "-fsS", "http://127.0.0.1:8080/actuator/health"],
  "success_contains": ["UP"],
  "failure_contains": ["DOWN", "Exception"],
  "timeout": 30,
  "deps": ["deploy"]
}
```

If any `failure_contains` string appears in output, the step becomes `FAILED`. `success_contains` is checked after exit 0 and all strings must appear; if any are missing, the step becomes `FAILED`.

## Next Steps

- Calling from an AI Agent → [MCP API](./mcp-api.en.md)
- Working directly with REST/SSE → [REST API](./rest-api.en.md)
- Production deployment / network binding → [Operations](./operations.en.md)
- Design background / domain rules → [00-overview.md](./00-overview.md) → [03-system-spec.md](./03-system-spec.md)
