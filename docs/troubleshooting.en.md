# Troubleshooting

A collection of symptoms encountered in practice. Add new cases via PR.

## Installation · Environment

### `greenlet` missing error on Python 3.14

```
ValueError: the greenlet library is required to use this function.
```

Fix:

```sh
backend/.venv/bin/pip install "greenlet>=3.0"
```

This is already specified in `backend/pyproject.toml`, so re-running `make setup` also resolves it.

### `no such column: jobs.params` / `runs.params` / `runs.outputs` after upgrading

The new version's DB migrations (`0003_run_params`, `0004_run_outputs`, `0005_single_running_run`, etc.) have not been applied. The table auto-creation at server start does not add columns to existing tables.

```sh
make migrate
```

Then restart the servers. See [Operations — Upgrading](./operations.en.md#upgrading).

### UI unchanged after upgrading (`make start` / `make start-bg`)

Production mode serves `frontend/dist` and does not rebuild it when `dist` already exists. Run `make build`, then restart.

### `curl http://127.0.0.1:5173` fails

Vite's default dev server binds to `localhost` (IPv6-first) only.

- Use `curl http://localhost:5173/`, or
- Add `server.host = '0.0.0.0'` to `vite.config.ts`, or
- Use `make dev-lan` (see [Operations](./operations.en.md)).

## MCP

### MCP call fails with `406 Not Acceptable` / `415` / `400`

- `406` — the `Accept: application/json, text/event-stream` header is missing.
- `415` — `Content-Type` is not `application/json`.
- `400` — the body is not a valid JSON-RPC message.

The server runs in stateless mode, so no `Mcp-Session-Id` is needed. See [MCP API §3](./mcp-api.en.md#3-direct-json-rpc-calls) for full curl examples.

### MCP call returns `401 UNAUTH`

- The `Authorization: Bearer <token>` header is missing, or
- The plaintext token does not match the DB hash, or
- The key has expired or been revoked.

Check key list and status via the UI `MCP Key` screen or `GET /api/keys`.

### MCP tool call returns `DENY: scope '…' not permitted`

The HTTP status is 200, but the tool result is an error (`isError: true`). The key's scope does not match the tool's required scope. Examples:

- Calling `run_job` with a `read:jobs`-only key → DENY
- Calling `run_job(job_id="bar")` with a `run:foo`-only key → DENY

See [MCP API §2](./mcp-api.en.md#2-scope-rules) for scope matching rules.

### A run started over MCP does not show live in the UI Monitor / SSE

A run triggered over MCP executes inside the MCP server process, and its live events exist only there. The backend's `GET /api/runs/{id}/stream` receives only heartbeats. Status and results are written to the DB, so check them with `GET /api/runs/{id}` or MCP `get_run`, and read logs with `GET /api/runs/{id}/logs/{step_id}`.

## Execution

### Run trigger rejected with `UNKNOWN_PARAM` / `INVALID_PARAM`

- `UNKNOWN_PARAM` — a name the Job does not declare was sent. Sending `params` to a Job that declares none is also this error. Check the Job's `params` (`GET /api/jobs/{id}`, MCP `get_job`).
- `INVALID_PARAM` — a param without a default was omitted, or the value does not match the whole `pattern`, is not a string, or is empty / has leading or trailing whitespace / contains control characters / exceeds 1024 characters. The message names the param and the reason.

See [Run Params](./run-params.en.md) for the full rules.

### A step printed `::output` but the run's `outputs` is empty

Look for warnings in the step log.

- `output ignored: …` — malformed (not `key=value`, bad key, empty value / leading or trailing whitespace / control characters / over 1024 characters)
- `outputs discarded: step ended FAILED` — only steps that end SUCCESS have their outputs recorded
- No warning at all means the line went to stderr (`echo … >&2`) or did not start with `::output ` at the very beginning

See [Run Outputs](./run-outputs.en.md) for the full rules.

### `cd /path` step is rejected with `policy.violation`

This is intentional. `cd` is shell/process state, and running it in a separate subprocess would not change the working directory of later steps. Use the step-level `cwd` field.

```json
{
  "id": "deploy",
  "cwd": "/opt/taskflow/apps/api",
  "cmd": ["./deploy.sh"]
}
```

`pushd` and `popd` are rejected for the same reason.

### Run stays at `RUNNING` and does not progress

In current versions, subprocess start failures such as missing executables, permission errors, and invalid `cwd` values are finalized as step `FAILED`. If the run was left behind by an older version, cancel it from Dashboard / Job Detail / Logs, or call `POST /api/runs/{id}/cancel`.

Check the backend logs for `Task exception was never retrieved`. Most commonly:

- The target command does not exist (`ENOENT`)
- The explicit `cwd` does not exist or is not a directory
- Rejected by policy (e.g. `cd`/`pushd`/`popd` as a step command), but the UI is still polling for status

Stderr is recorded in `backend/storage/logs/<run_id>/<step_id>.log`.

### Trigger returns `409 CONFLICT` although nothing is running

The database allows one `RUNNING` run per job, shared by the backend and the MCP server. If a server stops mid-run, the run stays `RUNNING` until that server starts again, which finalizes its own leftover runs as `FAILED` (`서버 재시작으로 중단`). It leaves the other server's runs alone, so a run left by a server that has not restarted keeps blocking the job.

Runs started before `0005_single_running_run` do not record which server ran them and are not finalized automatically. Cancel the `current_run_id` from the 409 response (over MCP: `… already running as #<run_id>`) with `POST /api/runs/{id}/cancel`, then trigger again.

### Step exits 0 but becomes `FAILED`

Check whether the step has output assertions configured.

- If any `failure_contains` string appears in stdout/stderr, the step fails.
- If any `success_contains` string is missing, the step fails.

Check the `output assertion failed: ...` message in run logs together with `backend/storage/logs/<run_id>/<step_id>.log`.

### Run ends with `TIMEOUT`

The Step's `timeout` field (in seconds) may be set too short. Adjust the timeout in Builder and re-run.

## Audit Log

### Audit chain verify returns FAIL

A DB row has been manually tampered with, or there may be a timezone handling bug.

```sh
curl http://localhost:8000/api/audit/verify
# FAIL: broken at id=128
```

The chain is broken starting from the event with id 128. This should never occur in normal operation. Steps to address:

1. Dump events near 128 with `GET /api/audit?limit=200`
2. If tampering is suspected, immediately back up the DB and record the incident
3. If normalization is needed, run `make reset` (warning: all Jobs/Runs/Keys/Audit data will be lost)

## Frontend

### Dashboard is empty

This is expected — the DB starts empty. Begin with `+ New Job`. See [Getting Started](./getting-started.en.md).

### SSE stream disconnects

- In a reverse proxy (Nginx/Cloudflare, etc.), set `proxy_buffering off` and increase `proxy_read_timeout`
- After 30+ seconds of idle, `event: ping` is automatically injected to keep the connection alive
