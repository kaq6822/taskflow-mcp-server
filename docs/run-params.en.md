# Run Parameters Guide

**🌐 Language / 언어:** [한국어](./run-params.md) · [English](./run-params.en.md)

How to pass **values that change on every run** — the branch to build, a deploy target — without editing the Job.

```
① Declare on the Job       ② Pass at trigger time       ③ Use in a step
┌──────────────────────┐  ┌───────────────────────┐  ┌──────────────────────┐
│ params: [{           │  │ params:               │  │ $PARAM_BRANCH        │
│   name: "branch",    │─▶│   {"branch":          │─▶│ = "feature/x"        │
│   default: "dev",    │  │    "feature/x"}       │  │                      │
│   pattern: "…"}]     │  └───────────────────────┘  └──────────────────────┘
└──────────────────────┘             │
                        Pinned on the run: params: {"branch": "feature/x"}
```

Same principles as artifact aliases: **undeclared names are rejected**, resolved values are pinned on the run once, and a step's `env` cannot override them.

---

## 1. Declaring on a Job

| Field | Required | Description |
|---|---|---|
| `name` | ✅ | `^[A-Za-z][A-Za-z0-9_]*$`. Steps receive it upper-cased as `PARAM_<NAME>`. No case-insensitive duplicates |
| `default` | | Used when a run omits the param. **`null` makes the param required** |
| `pattern` | | Python regex matched against the **whole** value (`fullmatch`). The `default` must pass it too, or the Job is not saved |

> **Without a `pattern`, any caller with run permission (`run:<job_id>`) can pass arbitrary strings — spaces, values starting with `-`, and so on.** The server itself only rejects empty values, leading/trailing whitespace, control characters (including newlines), invalid UTF-8, and values over 1024 characters. When a value ends up as a command argument, always set a pattern and forbid a leading `-` (restrict the first character as in the example). Always quote it in scripts: `"$PARAM_X"`. Patterns are matched on the event loop, so avoid nested repetition like `([a-z]+)+` — a caller with run permission could stall the server with a long value.

```bash
curl -X POST http://localhost:8000/api/jobs \
  -H 'Content-Type: application/json' \
  -d '{
    "id": "be-deploy",
    "name": "Backend deploy",
    "owner": "ops",
    "params": [
      {"name": "branch", "default": "dev", "pattern": "[A-Za-z0-9._][A-Za-z0-9._/-]*"}
    ],
    "steps": [
      {"id": "deploy", "cmd": ["/bin/bash", "/opt/deploy/backend.sh"], "timeout": 900, "deps": []}
    ]
  }'
```

In the web UI, use **Builder → Run params (optional)** for name · default · pattern. Leaving the default empty makes the param required.

## 2. Passing values at trigger time

Omitted params use their default. Names are case-insensitive (`BRANCH` works too).

```bash
# REST
curl -X POST http://localhost:8000/api/jobs/be-deploy/runs \
  -H 'Content-Type: application/json' -d '{"params": {"branch": "feature/x"}}'
```

```
# MCP
run_job(job_id="be-deploy", mode="async", params={"branch": "feature/x"})
```

In the web UI, **▷ Run** on a Job that declares params opens a prompt prefilled with the defaults. **Re-run** on the step-logs screen opens it with the values that run used.

## 3. Using them in a step

`cmd` runs with `shell=False`, so `$PARAM_BRANCH` in argv is not expanded. **Read it as an environment variable inside a script.**

```bash
#!/usr/bin/env bash
set -euo pipefail
: "${PARAM_BRANCH:?}"
git check-ref-format --branch "$PARAM_BRANCH" >/dev/null   # on top of the pattern
git fetch origin "$PARAM_BRANCH"
git checkout -B build "origin/$PARAM_BRANCH"
```

Each step log starts with `params · PARAM_BRANCH=feature/x`. **Values are kept verbatim in logs and on the run record — never pass secrets as params.**

## 4. Error codes

| Code | REST | Meaning |
|---|---|---|
| `UNKNOWN_PARAM` | 400 | Passed a name the Job does not declare |
| `INVALID_PARAM` | 400 | Required param missing · `pattern` mismatch · not a string · empty · leading/trailing whitespace · contains control characters · invalid UTF-8 · over 1024 chars · same name given twice |

A rejected trigger creates no run and is audited with `result=DENY`. Sending `params` to a Job that declares none is also `UNKNOWN_PARAM` — it is not silently ignored.
