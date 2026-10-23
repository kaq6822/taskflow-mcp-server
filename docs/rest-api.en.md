# REST API

The Backend REST API is served at `http://localhost:8000`. The Frontend (Vite dev) proxies `/api/*` to this address. In production (`make start`), the Backend serves both the SPA and API on the same port.

> `/api/*` has **no authentication**. MCP keys and scopes apply only to the MCP server (`:7391`). The audit log's `who` is taken as-is from the `X-Actor` request header (default `admin`) or the body's `actor`/`uploader`. See [Security](./security.en.md).

## Endpoints

| Method · Path | Description |
|---|---|
| `GET /api/health` | Health check (`{status, env}`) |
| `GET /api/jobs` | List jobs (most recently updated first) |
| `GET /api/jobs/{id}` | Job details |
| `POST /api/jobs` | Create job (201). `409` if the id already exists |
| `PATCH /api/jobs/{id}` | Update job. Only the fields sent change; a `null` value is treated as "not sent" |
| `DELETE /api/jobs/{id}` | Delete job (204), along with its run history. `409 {error: "CONFLICT", current_run_id}` while a run is in progress |
| `POST /api/jobs/{id}/runs` | Trigger a run (201, returns the run). Body: `{trigger?, actor?, artifact_refs?, params?, idempotency_key?}` — `trigger` is `manual` (default) / `schedule` / `mcp`, `actor` defaults to `web`. `artifact_refs` is `{alias: "uploads://<name>@<ver\|latest>"}`; omitted aliases use `@latest`. `params` is `{name: value}`; omitted params use their default ([Run parameters](./run-params.en.md)). Re-sending the same `idempotency_key` returns the existing run |
| `GET /api/runs?job_id=&status=&limit=` | Run history (newest first, `limit` default 50, max 500). E.g. outputs of the last successful run → `?job_id=…&status=SUCCESS&limit=1` |
| `GET /api/runs/{id}` | Single run (includes `steps[]`, `params`, `outputs` — [Run outputs](./run-outputs.en.md)) |
| `GET /api/runs/{id}/logs/{step_id}?tail=200` | Step stdout/stderr log tail (`text/plain`, `tail` 1–2000) |
| `POST /api/runs/{id}/cancel` | Cancel run. `404` if it is not running |
| `POST /api/jobs/{id}/runs/cancel` | Cancel the currently running run for a job |
| `GET /api/runs/{id}/stream` | SSE — `run.started` / `step.started` / `step.log` / `step.finished` / `run.finished` |
| `GET /api/artifacts` | List artifacts (most recent upload first) |
| `GET /api/artifacts/{id}` | Single artifact |
| `POST /api/artifacts` | Multipart upload (`name`, `version`, `ext`, `uploader`, `file`). `409` for an existing `name@version` |
| `GET /api/audit?kind=&result=&q=&limit=` | Query audit events |
| `GET /api/audit/verify` | Hash-chain integrity verification |
| `GET /api/audit/export.csv` | Export as CSV |
| `GET /api/keys` | List MCP keys |
| `POST /api/keys` | Issue key (plaintext shown once) |
| `DELETE /api/keys/{id}` | Revoke key |

## Job Fields

| Field | Description |
|---|---|
| `id` | Required. Job identifier (cannot be changed after creation) |
| `name` · `owner` | Required |
| `description` · `tags` | Optional |
| `schedule` | Default `manual`. A cron string is stored and displayed, but **no scheduler fires it (not implemented)** |
| `timeout` | Default 600. **Job-level timeout enforcement is not implemented** — only per-step `timeout` applies |
| `concurrency` | Default 1. Regardless of the value, a job has at most one run in progress |
| `on_failure` | Default used when a step has no `on_failure` (`STOP` by default) |
| `consumes_artifacts` | `[{alias, name}]` — [Artifacts](./artifacts.en.md) |
| `params` | `[{name, default, pattern}]` — `default: null` makes it required. [Run parameters](./run-params.en.md) |
| `steps` | Required. Array of the step fields below |

## Job Step Fields

`steps[]` entries in `POST /api/jobs` and `PATCH /api/jobs/{id}` use these fields:

| Field | Description |
|---|---|
| `id` | Step id, unique within the job |
| `cmd` | argv array executed with `shell=False`; shell command strings are rejected |
| `cwd` | Optional. Step working directory. Defaults to `TASKFLOW_STEP_CWD` |
| `success_contains` | Optional. Strings that must all appear in stdout/stderr after exit 0 |
| `failure_contains` | Optional. Strings that fail the step if any appear in stdout/stderr |
| `timeout` | Step timeout in seconds (default 60) |
| `deps` | Array of upstream step ids |
| `on_failure` | `STOP` / `CONTINUE` / `RETRY` (one retry) / `ROLLBACK` (currently same as `STOP`) |
| `env` | Step-specific environment variables. Reserved keys such as `PARAM_*` and `ARTIFACT_*` cannot be overridden ([Security](./security.en.md)) |

`cd`, `pushd`, and `popd` cannot be used as step commands. Set the working directory with `cwd` instead.

`failure_contains` is applied before exit-code handling. `success_contains` is checked only after the process exits with code 0; if any required string is missing, the step becomes `FAILED`.

## SSE Event Format

```
event: run.started     data: {run_id, job_id, at, artifacts, params}
event: step.started    data: {step_id, cmd, timeout}
event: step.log        data: {step_id, ts, lvl, text}
event: step.finished   data: {step_id, state, elapsed_sec}
event: run.finished    data: {run_id, status, failed_step, err_message, duration_sec}
event: ping            data: {}            # heartbeat after 30 seconds without events
```

- In `run.started`, `artifacts` is `{alias: "uploads://<name>@<version>"}` (the pinned references) and `params` holds the param values pinned on the run.
- `step.log`'s `lvl` is `cmd` (the command) / `dim` (meta: cwd·timeout, `artifacts · …`, `params · …`, `outputs · …`, etc.) / `info` (stdout) / `err` (stderr, failures) / `warn` / `ok`.
- Events emitted before you subscribe are replayed first (up to the most recent 500 kept in process memory); the stream closes after `run.finished`.
- A run triggered over MCP executes in the same process and log_bus, so this endpoint receives its events too.

You can subscribe directly from the browser using `EventSource('/api/runs/{id}/stream')`.

## Error Codes

Error bodies use FastAPI's `{"detail": …}` shape. For a rejected run trigger or a concurrency conflict `detail` is an object `{"error": "<code>", …}`; for other errors `detail` is a message string.

| HTTP | `detail.error` | Meaning |
|---|---|---|
| `400` | `INVALID_ARTIFACT` / `UNKNOWN_ALIAS` / `MISMATCH` | Artifact reference resolution failed ([Artifacts §5](./artifacts.en.md#5-error-codes)) |
| `400` | `UNKNOWN_PARAM` / `INVALID_PARAM` | Param resolution failed ([Run parameters §4](./run-params.en.md#4-error-codes)) |
| `404` | `NOT_FOUND` | Referenced artifact does not exist |
| `409` | `NOT_READY` | Artifact is not `READY` |
| `409` | `CONFLICT` | A run of the same job is already in progress (with `current_run_id`) · `idempotency_key` used by another job (`current_run_id: null`) · deleting a running job |
| `400` | (string) | Job save validation failed — DAG (cycle, unknown deps, argv shape), `cd`/`pushd`/`popd`, alias/params declaration errors · malformed upload fields |
| `404` | (string) | job/run/step/log/key not found, no running run to cancel |
| `409` | (string) | Job id already exists · artifact `name@version` already exists |
| `422` | (validation list) | Request body does not match the schema |

A rejected run trigger creates no run and is recorded in the audit log as `job.run` (result=DENY). `401 UNAUTH`, `429 RATE_LIMIT` and `DENY` only occur on the MCP server ([MCP API §4.1](./mcp-api.en.md#41-error-responses)).

A job's own `FAILED`/`TIMEOUT` is not an HTTP error — it is delivered as the `status` field in the response body.

## Related

- Tool calls via MCP → [MCP API](./mcp-api.en.md)
- Port / binding / CORS settings → [Operations](./operations.en.md)
- Security model → [Security](./security.en.md)
