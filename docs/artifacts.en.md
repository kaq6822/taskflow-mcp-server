# Artifacts Guide

How to upload build outputs (jar, tar.gz, images, …) to TaskFlow and have a Job's steps consume them **as a filesystem path**.

There is one core idea. **Steps never locate an artifact themselves.** A Job declares what it consumes under an alias, and TaskFlow picks a version at trigger time, pins it, and hands the path to every step as environment variables.

```
① Upload                ② Declare on the Job         ③ Use in a step
┌──────────────┐      ┌───────────────────┐      ┌────────────────────────┐
│ myapp@v1.2.0 │─────▶│ consumes_artifacts│─────▶│ $ARTIFACT_JAR_PATH     │
│ (file + sha) │      │ [{alias:"jar",    │      │ /…/storage/artifacts/  │
└──────────────┘      │   name:"myapp"}]  │      │   ab/myapp-v1.2.0.jar  │
                      └───────────────────┘      └────────────────────────┘
                                  │
                        ④ Version pinned when the Run starts
                        artifact_refs: {"jar": {ref:"uploads://myapp@v1.2.0", sha256:"…"}}
```

The alias (`jar`) is kept separate from the artifact name (`myapp`) for two reasons: renaming an artifact does not break the variables deploy scripts read, and the `.`/`-` characters allowed in names would collide as env keys (`my-app` and `my.app` both fold to `MY_APP`).

---

## 1. Upload

Three paths, same result.

### Web UI

**Artifacts** screen → **Upload** (top right) → fill `name` · `version` · `ext`, pick a file → upload.

### REST

Send as `multipart/form-data`.

```bash
curl -X POST http://localhost:8000/api/artifacts \
  -F name=myapp \
  -F version=v1.2.0 \
  -F ext=jar \
  -F uploader=ci \
  -F file=@build/myapp.jar
```

| Field | Required | Default | Description |
|---|---|---|---|
| `name` | ✅ | — | Artifact name. Jobs declare this name |
| `version` | ✅ | — | Version string. Meaning is up to you (`v1.2.0`, `build-417`, a commit SHA) |
| `ext` | | `tar.gz` | Extension. Used only in the stored filename |
| `uploader` | | `admin` | Recorded as the actor in the audit log |
| `file` | ✅ | — | File body |

### MCP (Agent)

```
upload_artifact(name="myapp", version="v1.2.0", content_base64="<base64>", ext="jar")
```

Requires scope `write:uploads`. Returns `{artifact_id, name, version, sha256, status, size_bytes}`.

### What an upload does

1. Computes SHA-256 while streaming the body
2. Stores it at `storage/artifacts/<first 2 chars of sha256>/<name>-<version>.<ext>` and locks it **0444 (read-only)**
3. Clears the previous `latest` flag for that name and marks the new row `latest`
4. Appends an `artifact.upload` audit event (`target=<name>@<version>`)

### Constraints

| Rule | On violation |
|---|---|
| `name` · `version` · `ext` allow only `[A-Za-z0-9._-]`, and reject `..`, `/`, `\` | `400` (path traversal guard) |
| `(name, version)` must be unique | `409 already exists` |

> **A version cannot be overwritten.** To re-upload, use a new version string. This is deliberate: it stops the contents of an already-deployed version from silently changing.

---

## 2. Declare it on the Job

A Job lists what it consumes in `consumes_artifacts` as `{alias, name}` entries. **An artifact that is not declared is invisible to the steps.**

### Web UI

**Builder** → **Consumes artifacts (optional)** in the Job meta panel → `+ Add` a row, then enter the alias and the artifact name. As you type, the `ARTIFACT_<ALIAS>_PATH` keys the steps will receive are previewed right below.

### REST

```bash
curl -X POST http://localhost:8000/api/jobs \
  -H 'Content-Type: application/json' \
  -d '{
    "id": "deploy-app",
    "name": "Deploy App",
    "owner": "ops",
    "consumes_artifacts": [
      {"alias": "jar",  "name": "myapp"},
      {"alias": "conf", "name": "myapp-config"}
    ],
    "steps": [
      {"id": "deploy", "cmd": ["/bin/bash", "/opt/taskflow/scripts/deploy.sh"], "timeout": 300, "deps": []}
    ]
  }'
```

### Alias rules

| Rule | Description |
|---|---|
| `^[A-Za-z][A-Za-z0-9_]*$` | Starts with a letter; letters, digits and `_` only. No `-` or `.` |
| No case-insensitive duplicates | `jar` and `JAR` cannot both be declared |
| No count limit | Declare as many as you need |

---

## 3. Use it in a step

Each declared alias injects these five variables into **every step**.

| Variable | Example value |
|---|---|
| `ARTIFACT_<ALIAS>_PATH` | `/…/storage/artifacts/ab/myapp-v1.2.0.jar` |
| `ARTIFACT_<ALIAS>_NAME` | `myapp` |
| `ARTIFACT_<ALIAS>_VERSION` | `v1.2.0` |
| `ARTIFACT_<ALIAS>_SHA256` | `ab12…` |
| `ARTIFACT_<ALIAS>_REF` | `uploads://myapp@v1.2.0` |

`<ALIAS>` is **upper-cased**: a `jar` declaration becomes `ARTIFACT_JAR_PATH`.

`deploy.sh` for the Job above would look like this.

```bash
#!/usr/bin/env bash
set -euo pipefail

echo "deploying $ARTIFACT_JAR_REF (sha256=$ARTIFACT_JAR_SHA256)"

# The stored file is read-only — copy it before working on it
cp "$ARTIFACT_JAR_PATH" ./app.jar
cp "$ARTIFACT_CONF_PATH" ./application.yml

java -jar ./app.jar --spring.config.location=./application.yml
```

Each step's log opens with the references it received, e.g. `artifacts · uploads://myapp@v1.2.0 · uploads://myapp-config@v7`.

### ⚠️ You cannot use `$ARTIFACT_*` directly in `cmd`

Steps run with `shell=False` (`subprocess.Popen(argv)`). argv elements are never shell-expanded, so this does **not** work:

```json
"cmd": ["cp", "$ARTIFACT_JAR_PATH", "./app.jar"]
```

`cp` receives the literal string. The variables must be read **inside the program the step runs** — wrap them in a script as above, or use a program that reads the environment itself.

```json
"cmd": ["/bin/bash", "/opt/taskflow/scripts/deploy.sh"]
```

### ⚠️ The step command must be in the allowlist

`/bin/bash` is **not** in the default allowlist. To handle artifacts from a script, add it to `backend/app/dev/allowlist.yaml` and restart the backend; otherwise saving the Job is rejected with `argv not in allowlist: /bin/bash`. **Register the script by absolute path** — a relative entry would authorise any same-named script in any directory. See [Artifact Jobs §0](./artifact-jobs.md) and [Security](./security.en.md).

### Other things to watch for

- **The file is locked 0444.** You cannot modify or extract it in place, so copy it first if you need to.
- **A step's `env` cannot override `ARTIFACT_*`.** These are merged after step env, and an attempt to override them logs `step env ignored for reserved keys: …`. This keeps the version recorded on the Run from disagreeing with the file that was actually deployed.
- **A step's default working directory is `storage/runtime`.** To run a script by relative path like `deploy.sh`, the file must live there, or the step must set `cwd`.

---

## 4. Choosing a version at trigger time

### Default: the latest upload

Omit `artifact_refs` and every declared alias resolves to `@latest`.

```bash
curl -X POST http://localhost:8000/api/jobs/deploy-app/runs \
  -H 'Content-Type: application/json' -d '{}'
```

> **`latest` means "most recently uploaded"**, not "highest version string". Upload `v2.0.0` and then `v1.9.0`, and `latest` is `v1.9.0`.

### Pin a version explicitly

Give a reference per alias. A partial map is fine — the rest fall back to `@latest`.

```bash
curl -X POST http://localhost:8000/api/jobs/deploy-app/runs \
  -H 'Content-Type: application/json' \
  -d '{
    "artifact_refs": {
      "jar": "uploads://myapp@v1.1.0"
    }
  }'
```

References are `uploads://<name>@<version|latest>`. Alias keys are **case-insensitive** — `JAR` addresses a `jar` declaration.

An explicitly blank reference is rejected with `INVALID_ARTIFACT` rather than falling back to `@latest`: when automation computes a reference and produces an empty value, failing is safer than silently deploying a version nobody asked for.

The same applies over MCP.

```
run_job(job_id="deploy-app", mode="sync", artifact_refs={"jar": "uploads://myapp@v1.1.0"})
```

### What pinning buys you

Resolution happens **once**, when the Run starts, and the result is stored on the Run record.

```json
{
  "artifact_refs": {
    "jar":  {"ref": "uploads://myapp@v1.2.0", "sha256": "ab12…"},
    "conf": {"ref": "uploads://myapp-config@v7", "sha256": "cd34…"}
  }
}
```

That guarantees two things.

- If someone uploads a new version mid-run and moves the `latest` pointer, every step of that Run still sees the same version
- Auditing months later shows a **concrete version and sha256** instead of `@latest`, so the exact build that was deployed is identifiable

The SSE `run.started` event carries the pinned references too.

---

## 5. Error codes

| Code | REST | Meaning | What to do |
|---|---|---|---|
| `NOT_FOUND` | 404 | The referenced artifact does not exist | Check the name/version and whether it was uploaded |
| `NOT_READY` | 409 | The artifact is not `READY` | Wait until it becomes `READY` |
| `UNKNOWN_ALIAS` | 400 | Passed an alias the Job does not declare | Check the Job's `consumes_artifacts` |
| `MISMATCH` | 400 | The reference points at a different artifact than declared | Align the alias with the reference's name |
| `INVALID_ARTIFACT` | 400 | Malformed reference · blank reference · duplicated alias | Check the `uploads://<name>@<ver>` form |

Error bodies are `{"detail": {"error": "<code>", "message": "<detail>"}}`, and a rejected trigger is recorded in the audit log with `result=DENY`.

If an artifact disappears between the trigger and the launch, the Run is failed immediately rather than left in `RUNNING`.

---

## 6. FAQ

**Q. `ARTIFACT_JAR_PATH` never reaches my step**
Check that the alias is declared in the Job's `consumes_artifacts`. Uploading alone injects nothing.

**Q. I want to re-upload the same version**
Not possible (`409`). Use a new version string.

**Q. I want to delete an artifact**
There is currently no delete endpoint and no prune. Files under `storage/artifacts/` accumulate, so capacity is managed out of band. Deleting a file by hand leaves the DB row behind, so it surfaces as a file-access failure during the run rather than `NOT_FOUND`.

**Q. When does `SCANNING` happen?**
Virus scanning is a stub in the current implementation, so uploads become `READY` immediately. The `NOT_READY`/`SCANNING` paths exist for when a real scanner is wired in.

**Q. How many artifacts can one Job consume?**
No limit, as long as the aliases differ.

---

## Related

- [Artifact Jobs](./artifact-jobs.en.md) — How to actually author Jobs that use artifacts (recipes, anti-patterns)
- [Getting Started](./getting-started.en.md) — Installation and your first Job
- [REST API](./rest-api.en.md) — Full endpoint list
- [MCP API](./mcp-api.en.md) — Agent tools and scopes
- [Security](./security.en.md) — allowlist, secret masking, audit log
