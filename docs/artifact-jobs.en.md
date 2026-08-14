# Authoring Jobs That Use Artifacts

Where the [Artifacts guide](./artifacts.en.md) covers *how artifacts work*, this document answers **"so how do I write the Job?"** It collects skeletons and patterns you can copy and adapt.

---

## 0. Prerequisite: allowlist the interpreter

A Job that handles artifacts almost always runs a script. But a step's `cmd` runs with `shell=False`, and the command must be **registered in the argv allowlist**. `/bin/bash` is not there by default.

Edit `backend/app/dev/allowlist.yaml` (run `make bootstrap-allowlist` if it does not exist).

```yaml
allow:
  - ["echo"]
  - ["printf"]
  - ["cat"]
  - ["/bin/bash", "/opt/taskflow/scripts/deploy.sh"]   # only this script
  - ["/bin/bash", "/opt/taskflow/scripts/verify.sh"]   # list each allowed script
  - ["/usr/bin/shasum"]
```

Each entry matches the **leading part (prefix) of argv**. `["echo"]` allows any invocation starting with `echo`; `["/bin/bash", "/opt/…/deploy.sh"]` allows only that script.

`*` is supported, but it is a **whole-element wildcard, not a path glob.**

| Entry | Matches `/bin/bash /opt/taskflow/scripts/deploy.sh`? |
|---|---|
| `["/bin/bash", "/opt/taskflow/scripts/deploy.sh"]` | ✅ exact match |
| `["/bin/bash", "*"]` | ✅ any second element |
| `["/bin/bash"]` | ✅ prefix-only, so anything goes |
| `["/bin/bash", "/opt/taskflow/scripts/*"]` | ❌ **no match** — compared literally against the string containing `*` |

So "only scripts in this directory" cannot be expressed. List each allowed script individually.

Also, because this is a **prefix** check, extra arguments after the registered elements are allowed: `["/bin/bash", "deploy.sh"]` also permits `/bin/bash deploy.sh --force`. To constrain the arguments too, include them in the entry.

> **`["/bin/bash"]` and `["/bin/bash", "*"]` let any script run.** Naming the script path as the second element is the safer shape.

A **backend restart** is required. Saving a Job with an unregistered command is rejected with `400`.

```json
{"detail": "argv not in allowlist: /bin/bash"}
```

---

## 1. The shortest skeleton

The minimum for consuming one artifact and deploying it.

**① Upload**

```bash
curl -X POST http://localhost:8000/api/artifacts \
  -F name=myapp -F version=v1.2.0 -F ext=jar -F uploader=ci -F file=@build/myapp.jar
```

**② Place the script** — in `storage/runtime/`, the default step working directory (or set `cwd` to use another location).

```bash
# storage/runtime/deploy.sh
#!/usr/bin/env bash
set -euo pipefail
cp "$ARTIFACT_JAR_PATH" ./app.jar     # the original is 0444, so copy it
java -jar ./app.jar
echo "DEPLOY_OK"
```

**③ Register the Job**

```json
{
  "id": "deploy-app",
  "name": "Deploy App",
  "owner": "ops",
  "consumes_artifacts": [{"alias": "jar", "name": "myapp"}],
  "steps": [
    {
      "id": "deploy",
      "cmd": ["/bin/bash", "deploy.sh"],
      "timeout": 300,
      "deps": [],
      "success_contains": ["DEPLOY_OK"]
    }
  ]
}
```

**④ Run** — omit `artifact_refs` and the latest upload is used.

```bash
curl -X POST http://localhost:8000/api/jobs/deploy-app/runs -d '{}'
```

---

## 2. Authoring checklist

| Step | Check | If missed |
|---|---|---|
| ① allowlist | Command is in `allowlist.yaml` and the backend was restarted | `400 argv not in allowlist` on save |
| ② script location | Lives in `storage/runtime/`, or the step sets `cwd` | `exit 127 executable not found` / `126 cwd not found` |
| ③ alias declared | The alias is in `consumes_artifacts` | `ARTIFACT_*` is never injected (silently empty) |
| ④ cmd | Variables are read **inside** the program | `$ARTIFACT_...` passed as a literal string |
| ⑤ verdict | Is the exit code enough to judge success? | Failures reported as success |

---

## 3. Step patterns

### 3.1 Ordering — `deps`

`deps` sets execution **order**. Steps run **sequentially** in topological order; independent steps do not run in parallel.

```json
"steps": [
  {"id": "verify",  "cmd": ["/bin/bash", "verify.sh"],  "timeout": 60,  "deps": []},
  {"id": "deploy",  "cmd": ["/bin/bash", "deploy.sh"],  "timeout": 300, "deps": ["verify"]},
  {"id": "health",  "cmd": ["/bin/bash", "health.sh"],  "timeout": 60,  "deps": ["deploy"]}
]
```

Cycles are rejected at save time with `cycle detected: a → b → a`, and referencing a step that does not exist is rejected with `depends on unknown step '…'`.

Once an earlier step fails the run, **every later step becomes `SKIPPED`**.

### 3.2 Verifying artifact integrity

`ARTIFACT_<ALIAS>_SHA256` is the digest computed at upload. You can compare it against the file before deploying.

```bash
# storage/runtime/verify.sh
#!/usr/bin/env bash
set -euo pipefail
actual=$(shasum -a 256 "$ARTIFACT_JAR_PATH" | cut -d' ' -f1)
if [ "$actual" != "$ARTIFACT_JAR_SHA256" ]; then
  echo "SHA_MISMATCH expected=$ARTIFACT_JAR_SHA256 actual=$actual"
  exit 1
fi
echo "SHA_OK $ARTIFACT_JAR_REF"
```

### 3.3 Output-based verdicts

When the exit code is not enough, use `success_contains` (text that must appear) and `failure_contains` (text that must not). Both are **substring** checks over stdout and stderr — not regular expressions.

```json
{
  "id": "deploy",
  "cmd": ["/bin/bash", "deploy.sh"],
  "timeout": 300,
  "deps": [],
  "success_contains": ["DEPLOY_OK"],
  "failure_contains": ["OutOfMemoryError", "Connection refused"]
}
```

Precedence:

| Situation | Result |
|---|---|
| `failure_contains` hit | **FAILED** — even with exit code 0 |
| exit 0 + all `success_contains` seen | SUCCESS |
| exit 0 + a `success_contains` missing | **FAILED** (`missing required text …`) |
| exit ≠ 0 | FAILED (`non-zero exit N`) |

The key point is that `failure_contains` is the strongest signal. It catches deploy tools that exit 0 while logging an error.

### 3.4 Failure handling — `on_failure`

Set it on a step to override the Job default.

| Value | Behavior |
|---|---|
| `STOP` | Mark later steps `SKIPPED` and finish the run FAILED (default) |
| `CONTINUE` | Move to the next step without failing the run |
| `RETRY` | Retry **once**. A successful retry clears the first attempt's failure record |
| `ROLLBACK` | ⚠️ Currently behaves **identically to `STOP`** |

> **`ROLLBACK` does not roll anything back.** If you need compensation, write the compensating step yourself and structure the preceding step (e.g. as `CONTINUE`) so control reaches it. Do not expect automatic rollback from the name.

Retry a flaky fetch while keeping the deployment itself fail-stop:

```json
"steps": [
  {"id": "fetch",  "cmd": ["/bin/bash", "fetch.sh"],  "timeout": 60,  "deps": [], "on_failure": "RETRY"},
  {"id": "deploy", "cmd": ["/bin/bash", "deploy.sh"], "timeout": 300, "deps": ["fetch"], "on_failure": "STOP"}
]
```

### 3.5 Combining several artifacts

An alias is the name the step sees, so naming it after the **role** rather than the artifact reads better.

```json
{
  "id": "release",
  "name": "Release",
  "owner": "ops",
  "consumes_artifacts": [
    {"alias": "app",       "name": "myapp"},
    {"alias": "conf",      "name": "myapp-config"},
    {"alias": "migration", "name": "myapp-db-migration"}
  ],
  "steps": [
    {"id": "migrate", "cmd": ["/bin/bash", "migrate.sh"], "timeout": 600, "deps": []},
    {"id": "deploy",  "cmd": ["/bin/bash", "deploy.sh"],  "timeout": 300, "deps": ["migrate"]}
  ]
}
```

All three aliases are injected into **every step**. `migrate.sh` reads `$ARTIFACT_MIGRATION_PATH`, `deploy.sh` reads `$ARTIFACT_APP_PATH` and `$ARTIFACT_CONF_PATH`. There is no way to scope an alias to a subset of steps.

Aliases must match `^[A-Za-z][A-Za-z0-9_]*$` and are deduplicated case-insensitively. A `-`, as in `db-migration`, is rejected on save.

### 3.6 Working directory — `cwd`

Omitted, it defaults to `storage/runtime`, which is created if missing. **Set it explicitly and the directory must already exist.**

```json
{"id": "deploy", "cmd": ["/bin/bash", "/opt/taskflow/scripts/deploy.sh"],
 "cwd": "/opt/taskflow/work", "timeout": 300, "deps": []}
```

A missing path fails with `exit 126 cwd not found: …`. `cd`, `pushd` and `popd` cannot be step commands (rejected on save) — express directory changes with `cwd`.

---

## 4. Anti-patterns

| Don't | Why | Instead |
|---|---|---|
| `"cmd": ["cp", "$ARTIFACT_JAR_PATH", "./a.jar"]` | `shell=False`, so it is passed as a literal | Wrap in a script and reference it there |
| `"cmd": ["cd", "/opt/app"]` | A child process cannot change the worker's cwd (rejected on save) | Use the step's `cwd` |
| Hard-coding an artifact path | Breaks on a version change and diverges from the pinned record | Use `$ARTIFACT_<ALIAS>_PATH` |
| Modifying/extracting the original in place | It is locked 0444 | Copy into the working directory first |
| Setting `ARTIFACT_*` in step `env` | Ignored, with a warning | Use a differently-named variable |
| `-` or `.` in an alias | Not usable as an env key | Use `_` (`db_migration`) |
| Relying on `@latest` for every run | Hard to identify which build shipped | Pin the version with `artifact_refs` for deploys |
| Expecting `on_failure: "ROLLBACK"` to undo | Behaves like `STOP` | Write a compensating step |

---

## 5. End-to-end: CI → Agent

CI uploads the build output; the Agent runs the Job against an explicit version.

**① CI: upload** (scope `write:uploads`)

```bash
curl -fsS -X POST "$TASKFLOW/api/artifacts" \
  -F name=myapp -F "version=$GIT_SHA" -F ext=jar \
  -F uploader=ci -F file=@build/myapp.jar
```

**② Agent: run with the version pinned** (scope `run:<job_id>`)

```
run_job(
  job_id="deploy-app",
  mode="sync",
  artifact_refs={"jar": "uploads://myapp@<GIT_SHA>"},
  idempotency_key="deploy-<GIT_SHA>"
)
```

With `idempotency_key`, calling again with the same key returns the existing run instead of creating a new one, so a retry does not become a double deploy.

**③ Confirm** — the response's `artifact_refs` records the concrete version and sha256 that were actually deployed.

```json
{
  "status": "SUCCESS",
  "artifact_refs": {"jar": {"ref": "uploads://myapp@a1b2c3d", "sha256": "…"}},
  "steps": [{"step_id": "deploy", "state": "SUCCESS"}]
}
```

---

## 6. Pre-deploy review

- [ ] Is the command in the allowlist, and no broader than it needs to be?
- [ ] Does the script start with `set -euo pipefail` so mid-script failures are not swallowed?
- [ ] Is the artifact copied before being worked on?
- [ ] Is the exit code enough, or is `success_contains` needed?
- [ ] Is `timeout` comfortably above the real duration? (exceeding it yields `TIMEOUT`)
- [ ] Do deploy Jobs pin the version with `artifact_refs`?
- [ ] Are you expecting `ROLLBACK` to undo something?

---

## Related

- [Artifacts](./artifacts.en.md) — how upload, env vars and pinning work
- [Getting Started](./getting-started.en.md) — installation and your first Job
- [Security](./security.en.md) — allowlist design, secret masking, audit log
- [Troubleshooting](./troubleshooting.en.md) — symptom-based fixes
