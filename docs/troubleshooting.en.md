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

### `curl http://127.0.0.1:5173` fails

Vite's default dev server binds to `localhost` (IPv6-first) only.

- Use `curl http://localhost:5173/`, or
- Add `server.host = '0.0.0.0'` to `vite.config.ts`, or
- Use `make dev-lan` (see [Operations](./operations.en.md)).

## MCP

### MCP call fails with `400 Bad Request`

All MCP calls (except the initial `initialize`) require an `Mcp-Session-Id` header. Extract the value from the `initialize` response headers and include it in all subsequent calls.

Also required: `Accept: application/json, text/event-stream` header. See [MCP API §3](./mcp-api.en.md#3-direct-json-rpc-calls) for full curl examples.

### MCP call returns `401 UNAUTH`

- The `Authorization: Bearer <token>` header is missing, or
- The plaintext token does not match the DB hash, or
- The key has expired or been revoked.

Check key list and status via the UI `MCP Key` screen or `GET /api/keys`.

### MCP call returns `403 DENY`

The key's scope does not match the tool's required scope. Examples:

- Calling `run_job` with a `read:jobs`-only key → DENY
- Calling `run_job(job_id="bar")` with a `run:foo`-only key → DENY

See [MCP API §2](./mcp-api.en.md#2-scope-rules) for scope matching rules.

## Execution

### Job run immediately returns `policy.violation` for an allowlisted command

This is intentional behavior. Add the argv prefix to `backend/app/dev/allowlist.yaml` and restart the backend.

```yaml
allow:
  - ["npm", "ci"]
  - ["npm", "run", "build"]
  - ["aws", "s3", "sync"]
```

See [Security](./security.en.md) for policy background.

### Run stays at `RUNNING` and does not progress

Check the backend logs for `Task exception was never retrieved`. Most commonly:

- The target command does not exist (`ENOENT`)
- Rejected by allowlist mismatch, but the UI is still polling for status

Stderr is recorded in `backend/storage/logs/<run_id>/<step_id>.log`.

### Run ends with `TIMEOUT`

The Step's `timeout` field (in seconds) may be set too short. Adjust the timeout in Builder and re-run.

## Audit Log

### Audit chain verify returns FAIL

A DB row has been manually tampered with, or there may be a timezone handling bug.

```sh
curl http://localhost:8000/api/audit/verify
# { "ok": false, "broken_at": 128 }
```

The chain is broken starting from event 128. This should never occur in normal operation. Steps to address:

1. Dump events near 128 with `GET /api/audit?limit=200`
2. If tampering is suspected, immediately back up the DB and record the incident
3. If normalization is needed, run `make reset` (warning: all Jobs/Runs/Keys/Audit data will be lost)

## Frontend

### Dashboard is empty

This is expected — the DB starts empty. Begin with `+ New Job`. See [Getting Started](./getting-started.en.md).

### SSE stream disconnects

- In a reverse proxy (Nginx/Cloudflare, etc.), set `proxy_buffering off` and increase `proxy_read_timeout`
- After 30+ seconds of idle, `event: ping` is automatically injected to keep the connection alive
