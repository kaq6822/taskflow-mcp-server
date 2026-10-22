# Run Outputs Guide

**🌐 Language / 언어:** [한국어](./run-outputs.md) · [English](./run-outputs.en.md)

How a step **records a value on the run** — the commit it actually built, the version it produced. If [run parameters](./run-params.en.md) are what goes in, outputs are what comes out.

## 1. Publishing from a step

Print one line on stdout.

```bash
echo "::output commit=$(git rev-parse HEAD)"
echo "::output branch=$PARAM_BRANCH"
```

| Rule | Detail |
|---|---|
| Where | **stdout**, the line must start with `::output `. The same line on stderr is ignored |
| key | `^[A-Za-z][A-Za-z0-9_]*$` |
| value | Everything after the first `=` (a trailing `\r` is dropped). Empty values, control characters and values over 1024 chars are ignored with an `output ignored` warning in the log |
| Overwrites | Printing the same key again (same step, a retry, or a later step) keeps the last value |
| Failed steps | Outputs are kept even if the step fails — **decide whether to trust them by the run's `status`** |

The step log keeps the original line and ends with an `outputs · commit=…` summary.

## 2. Reading

Run responses (REST `RunOut`, MCP `get_run`/`list_runs`) carry them as `outputs: {key: value}`. The most common question — **"what was the value when this job last succeeded"** — is an existing query:

```bash
curl -s 'http://localhost:8000/api/runs?job_id=be-deploy&status=SUCCESS&limit=1' \
  | python3 -c 'import sys,json; r=json.load(sys.stdin); print(r[0]["outputs"].get("commit") if r else "")'
```

```
# MCP
list_runs(job_id="be-deploy", status="SUCCESS", limit=1)
```

In the web UI they appear at the top of the step-logs screen (`→ commit=…`) and in the `Outputs` column of a job's Runs table.

## 3. Caveats

- Outputs are stored verbatim in logs and on the run — **never print secrets as outputs.**
- An output is whatever the step reported. TaskFlow does not verify it.
