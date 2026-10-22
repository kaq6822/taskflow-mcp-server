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
| value | Everything after the first `=` (a trailing `\r` is dropped). Empty values, leading/trailing whitespace, control characters (C0/C1, U+2028/2029), replacement characters (U+FFFD) and values over 1024 chars are ignored with an `output ignored` warning in the log |
| Overwrites | Printing the same key again (same step or a later step) keeps the last value, with an `overwritten` warning when it changes |
| Failed steps | **Only a step that ends SUCCESS gets its outputs recorded.** Values from failed, timed-out or cancelled steps are discarded with an `outputs discarded` warning — so a run that succeeds through `CONTINUE` or `RETRY` never carries a failed attempt's values |

Print outputs near the end of a step. Arbitrary content streamed to stdout afterwards (commit messages, file contents) could contain an `::output` line that overwrites the value.

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
