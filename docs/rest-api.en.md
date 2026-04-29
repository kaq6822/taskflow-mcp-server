# REST API

The Backend REST API is served at `http://localhost:8000`. The Frontend (Vite dev) proxies `/api/*` to this address. In production (`make start`), the Backend serves both the SPA and API on the same port.

## Endpoints

| Method · Path | Description |
|---|---|
| `GET /api/health` | Health check |
| `GET /api/jobs` | List jobs |
| `GET /api/jobs/{id}` | Job details |
| `POST /api/jobs` | Create job |
| `PATCH /api/jobs/{id}` | Update job |
| `DELETE /api/jobs/{id}` | Delete job |
| `POST /api/jobs/{id}/runs` | Trigger a run (body: `{trigger, actor, artifact_ref?, idempotency_key?}`) |
| `GET /api/runs?job_id=&status=&limit=` | Run history |
| `GET /api/runs/{id}` | Single run (includes `steps[]`) |
| `POST /api/runs/{id}/cancel` | Cancel run |
| `POST /api/jobs/{id}/runs/cancel` | Cancel the currently running run for a job |
| `GET /api/runs/{id}/stream` | SSE — `run.started` / `step.started` / `step.log` / `step.finished` / `run.finished` |
| `GET /api/artifacts` | List artifacts |
| `POST /api/artifacts` | Multipart upload (`name`, `version`, `ext`, `uploader`, `file`) |
| `GET /api/audit?kind=&result=&q=&limit=` | Query audit events |
| `GET /api/audit/verify` | Hash-chain integrity verification |
| `GET /api/audit/export.csv` | Export as CSV |
| `GET /api/keys` | List MCP keys |
| `POST /api/keys` | Issue key (plaintext shown once) |
| `DELETE /api/keys/{id}` | Revoke key |

## Job Step Fields

`steps[]` entries in `POST /api/jobs` and `PATCH /api/jobs/{id}` use these fields:

| Field | Description |
|---|---|
| `id` | Step id, unique within the job |
| `cmd` | argv array executed with `shell=False`; shell command strings are rejected |
| `cwd` | Optional. Step working directory. Defaults to `TASKFLOW_STEP_CWD` |
| `timeout` | Step timeout in seconds |
| `deps` | Array of upstream step ids |
| `on_failure` | `STOP` / `CONTINUE` / `RETRY` / `ROLLBACK` |
| `env` | Step-specific environment variables |

`cd`, `pushd`, and `popd` cannot be used as step commands. Set the working directory with `cwd` instead.

## SSE Event Format

```
event: run.started     data: {run_id, job_id, at}
event: step.started    data: {step_id, cmd, timeout}
event: step.log        data: {step_id, ts, lvl, text}
event: step.finished   data: {step_id, state, elapsed_sec}
event: run.finished    data: {run_id, status, failed_step, err_message, duration_sec}
event: ping            data: {}            # heartbeat every 30 seconds
```

You can subscribe directly from the browser using `EventSource('/api/runs/{id}/stream')`.

## Error Codes

| HTTP | Meaning |
|---|---|
| `400 INVALID_ARTIFACT` | Hash / format mismatch |
| `401 UNAUTH` | Missing or invalid Bearer key |
| `403 DENY` | Scope mismatch |
| `404 NOT_FOUND` | job/run/artifact not found |
| `409 CONFLICT` | Concurrency block (includes `current_run_id`) |
| `429 RATE_LIMIT` | Rate limit exceeded (includes `retry_after`) |
| `202 SCANNING` | Artifact scan in progress |

A job's own `FAILED`/`TIMEOUT` is not an HTTP error — it is delivered as the `status` field in the response body.

## Related

- Tool calls via MCP → [MCP API](./mcp-api.en.md)
- Port / binding / CORS settings → [Operations](./operations.en.md)
- Security model → [Security](./security.en.md)
