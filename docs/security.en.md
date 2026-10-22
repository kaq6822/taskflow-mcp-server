# Security Model

TaskFlow is designed with the premise that AI Agents can execute arbitrary commands. There is no restriction on which commands a step may run — **anyone who can create or edit a Job can run arbitrary commands on the server.**

> ⚠️ **The Job create/edit REST API is currently unauthenticated.** Anyone who can reach `/api/jobs` can create and run a Job, so the only real barrier is **network access control**. MCP Key scopes apply solely to the MCP surface (`run:<job-id>` to run, `read:*` to read, `write:uploads` to upload) and **do not govern Job authoring** — MCP exposes no Job-creation tool at all. Do not expose the backend on an untrusted network.

Instead of restricting which commands may run, TaskFlow narrows the execution environment with the enforced policies below and records every action in the hash-chained audit log so it can be traced after the fact.

## Enforced Policies

### 1. `shell=False`

Step execution is exclusively via `subprocess.Popen(argv)` (no shell). There is no shell string execution path anywhere in the codebase — a step's `cmd` must be a non-empty list of strings (argv form), never a shell string. If argv is not a list, it is rejected at the DAG parsing stage. This blocks shell metacharacter tricks (`;`, `|`, `&&`, backticks, etc.), but it does **not** restrict which program is invoked.

### 2. Controlled cwd

Steps run from `./storage/runtime` by default. This default can be overridden with `TASKFLOW_STEP_CWD`.

If a job author needs a specific working directory for a step, use the step-level `cwd` field.

```json
{
  "id": "deploy",
  "cwd": "/opt/taskflow/apps/api",
  "cmd": ["./deploy.sh"],
  "timeout": 300
}
```

An explicit `cwd` is rejected if empty. At execution time, if it does not exist or is not a directory, the step ends as `FAILED`. `cd`, `pushd`, and `popd` cannot be used as step commands. Directory changes are shell/process state and do not carry over to later steps, so they must be represented with `cwd`.

### 3. `SECRET_*` Environment Variables

When the step environment (variables inherited from the server process + the step's `env`) contains keys starting with `SECRET_`, the run log shows **only their names**, as `env: secrets masked (SECRET_DB_PASSWORD, …)`. The engine never writes environment values to the log. This is not a value-redaction mechanism, though:

- If a step prints the value to stdout/stderr, it lands **verbatim** in the log file and the SSE stream.
- Values written in a step's `env` are part of the Job definition, **stored in plaintext in the DB**, and returned as-is by `GET /api/jobs` and MCP `list_jobs`/`get_job` (`read:jobs`).
- No `secret.read` audit event is recorded (not implemented).

Keep real secrets out of Job definitions: provide them through the environment of the backend / MCP server processes (steps inherit it) or a file the step script reads.

### 4. Reserved Environment Variables (`PARAM_*` · `ARTIFACT_*`)

[Run params](./run-params.en.md) (`PARAM_<NAME>`) and [artifacts](./artifacts.en.md) (`ARTIFACT_<ALIAS>_*`) are values pinned on the run. So that the run record and what actually executed cannot diverge:

- They are applied to the step environment **last**, so a step's `env` cannot override them. An attempt is ignored and logs a `step env ignored for reserved keys: …` warning.
- `PARAM_*` variables present in the server process environment are **not inherited** by steps — otherwise a value the run never recorded would look like a declared param.

Param values and outputs are **not treated as secrets.**

- Param values appear verbatim at the top of every step log (`params · PARAM_BRANCH=…`) and on the run record (`params`); [outputs](./run-outputs.en.md) likewise appear in the log (`outputs · …`) and on the run record (`outputs`). Never pass or print secrets through them.
- If a param is declared without a `pattern`, a caller holding only the run scope (`run:<job_id>`) can pass any string (whitespace, values starting with `-`, …). When a value reaches command arguments, set a `pattern` and keep the first character from being `-`.
- `pattern` is matched on the server's event loop. Avoid nested repetition such as `([a-z]+)+` (ReDoS): a caller with run permission could stall the server with a long value (up to 1024 characters).

### 5. Hash-chained Audit

![Audit Log screen](./assets/04-audit.png)

Every audit event is linked with a `prev_hash` + `sha256(canonical_body)` chain. Modifying any single event breaks the entire chain afterward.

```sh
curl http://localhost:8000/api/audit/verify
# OK: audit chain intact
```

Returns `FAIL: broken at id=N` (plain text) if tampering is detected. See [Troubleshooting](./troubleshooting.en.md) for response steps.

On the REST side an event's `who` is recorded as-is from the `X-Actor` header (default `admin`) or the body's `actor`/`uploader`, so REST actors are not verified identities. On the MCP side `who` is the key label.

### 6. MCP Key Protection

- Only a **hash** is stored in the DB. Plaintext is included in the response only once at issuance.
- Scope matching + per-key rate-limit (the chosen `10/min` · `30/min` · `60/min` over the last 60 seconds).
- Audit events: issue `mcp.key.issue`, revoke `mcp.key.revoke`, authentication failure or scope denial `auth.fail`, rate-limit exceeded `mcp.rate_limit`. Key rotation is not implemented — revoke and issue a new key.
- Expired keys are automatically rejected.

For scope rules, see [MCP API §2](./mcp-api.en.md#2-scope-rules).

## Why the Remaining Policies Cannot Be Bypassed

- **At job create/edit (UI/REST)** — DAG parser validates argv and `cwd` format + rejects shell strings / state-changing commands
- **Right before a step executes** — `policies.py` re-validates argv shape and state-changing commands (`cd`/`pushd`/`popd`), in case the DB was changed by another route
- **At subprocess time** — `subprocess.Popen(argv)` does not perform shell interpretation (direct execve)

A failure at save time is rejected with `400` and records a `policy.violation` (state-changing command) or `job.create`/`job.edit` (format error) DENY audit event. A failure right before execution marks that step `FAILED` and records a `policy.violation` DENY audit event. None of this checks *which* program is being run — only that it is expressed as argv and does not try to change directory out from under the worker.

## Out of Scope (Currently Not Implemented)

The following are outside the current security model scope:

- Network egress control (firewall/seccomp) — delegated to OS layer
- Container/namespace isolation — process isolation is currently limited to cwd control
- SIEM forward — only local audit table (`GET /api/audit/export.csv`)
- ClamAV real integration — currently stub (upload immediately READY)
- **REST API authentication** — no `/api/*` route has an auth dependency. `bootstrap.py` mints an admin session token, but nothing verifies it.
- **Secret value redaction · `secret.read` audit** — see §3. Beyond listing names, values are neither hidden nor access-logged.
- **Dedicated low-privilege account / no-root execution** — the worker passes no `user=` or uid drop to `subprocess.Popen`. Steps run as whatever account started the backend.

## Related

- Policy implementation details → `backend/app/engine/policies.py`
- Audit event types → [02-business-rules.md](./02-business-rules.md)
- MCP Key scope matching → [MCP API](./mcp-api.en.md)
