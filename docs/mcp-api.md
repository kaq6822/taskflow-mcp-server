# MCP API

TaskFlow MCP 서버는 **Streamable HTTP transport**로 동작합니다. 모든 호출은 `Authorization: Bearer <token>` 헤더가 필요합니다.

- 기본 URL: `http://localhost:7391/mcp`
- 프로토콜: JSON-RPC 2.0 (`initialize` → `notifications/initialized` → `tools/call`)
- 인증: MCP Key plaintext를 Bearer 토큰으로 전달

## 1. MCP Key 발급

![MCP Keys 화면](./assets/05-mcp-keys.png)

### UI에서 발급

`MCP Key` 화면 → `+ 새 Key 발급` → Label / Scope / 만료일 / Rate limit 선택. **Key는 발급 직후 단 1회만 화면에 표시**되므로 안전하게 복사해 두세요.

### CLI에서 발급

```sh
curl -s -X POST http://localhost:8000/api/keys \
  -H "Content-Type: application/json" \
  -d '{
    "label": "test-agent",
    "scopes": ["read:jobs", "read:runs", "run:hello"],
    "expires_days": 30,
    "rate_limit": "60/min"
  }'
```

응답 예:

```json
{
  "id": "k_...",
  "label": "test-agent",
  "plaintext": "mcp_tk_live_xxxxxxxxxxxxxxxxxxxxxxx",
  "scopes": ["read:jobs", "read:runs", "run:hello"],
  ...
}
```

`plaintext` 값은 **이 순간 한 번만** 얻을 수 있습니다. DB에는 hash만 저장됩니다.

## 2. Scope 규칙

| Scope | 의미 |
|---|---|
| `read:jobs` / `read:runs` / `read:*` | 조회 도구만 허용 |
| `run:<job-id>` | 특정 Job 실행 |
| `run:*` | 모든 Job 실행 |
| `write:uploads` | 아티팩트 업로드 |

매칭 규칙: 요구 scope와 정확히 같거나, 같은 네임스페이스의 `<ns>:*`(`run:*`, `read:*` 등)를 가지면 허용됩니다. Read-only Key로 `run_job`을 호출하면 tool 오류 `DENY: scope 'run:<job_id>' not permitted`가 반환되고 `auth.fail`(result=DENY) audit이 기록됩니다 — HTTP 403이 아니라 JSON-RPC 응답 안의 오류입니다(§4.1).

## 3. JSON-RPC로 직접 호출

서버는 **stateless** Streamable HTTP 모드(JSON 응답)로 동작합니다. 요청마다 독립적으로 처리되므로 `Mcp-Session-Id`를 발급하지 않고 요구하지도 않으며, `initialize` 없이 바로 `tools/list`·`tools/call`을 보내도 됩니다. 일반 MCP 클라이언트는 `initialize`부터 보내는데, 그것도 그대로 동작합니다.

```sh
TOKEN="mcp_tk_live_...(발급받은 plaintext)..."

# 1) 사용 가능한 도구 목록
curl -X POST http://localhost:7391/mcp \
  -H "Content-Type: application/json" \
  -H "Accept: application/json, text/event-stream" \
  -H "Authorization: Bearer $TOKEN" \
  -d '{"jsonrpc":"2.0","id":1,"method":"tools/list","params":{}}'

# 2) run_job (sync 모드)
curl -X POST http://localhost:7391/mcp \
  -H "Content-Type: application/json" \
  -H "Accept: application/json, text/event-stream" \
  -H "Authorization: Bearer $TOKEN" \
  -d '{"jsonrpc":"2.0","id":2,"method":"tools/call","params":{
       "name":"run_job",
       "arguments":{"job_id":"hello","mode":"sync"}}}'

# 3) 파라미터를 선언한 Job에 값 전달 (async 모드)
curl -X POST http://localhost:7391/mcp \
  -H "Content-Type: application/json" \
  -H "Accept: application/json, text/event-stream" \
  -H "Authorization: Bearer $TOKEN" \
  -d '{"jsonrpc":"2.0","id":3,"method":"tools/call","params":{
       "name":"run_job",
       "arguments":{"job_id":"be-deploy","mode":"async","params":{"branch":"feature/x"}}}}'
```

`run_job(mode=sync)` 응답은 Run이 종료될 때까지 블로킹되며 `content[0].text`에 다음 JSON(Agent 스키마)이 담깁니다. `get_run`·`list_runs`·`cancel_run`도 같은 형태입니다:

```json
{
  "run_id": 4821,
  "job_id": "hello",
  "status": "SUCCESS",
  "started_at": "...",
  "finished_at": "...",
  "duration_sec": 1.02,
  "artifact_refs": {},
  "params": {},
  "outputs": {},
  "steps": [
    {"id": "greet", "state": "SUCCESS", "elapsed_sec": 0.002},
    {"id": "wait",  "state": "SUCCESS", "elapsed_sec": 1.01}
  ],
  "failed_step": null,
  "err_message": null,
  "logs_uri": "taskflow://runs/4821/logs"
}
```

| 필드 | 내용 |
|---|---|
| `status` | `RUNNING` / `SUCCESS` / `FAILED` / `TIMEOUT`. 취소된 Run은 `FAILED` + `err_message: "사용자 취소"` |
| `artifact_refs` | alias별로 고정된 `{ref, sha256}` ([Artifacts](./artifacts.md)) |
| `params` | Run에 고정된 파라미터 값 전체(기본값 포함) ([Run 파라미터](./run-params.md)) |
| `outputs` | step이 `::output key=value`로 남긴 값 ([Run 출력값](./run-outputs.md)) |
| `steps[].state` | `PENDING` / `RUNNING` / `SUCCESS` / `FAILED` / `TIMEOUT` / `SKIPPED` |
| `logs_uri` | 식별용 URI. 로그 본문은 `get_run_logs(run_id, step_id)`로 가져옵니다 |

동시에 `audit` 테이블에 `mcp.run` (src=mcp), `job.run.done`(실패 시 `job.run.fail`) 이벤트가 기록됩니다.

## 4. 도구 목록

| Tool | 필요 Scope | 설명 |
|---|---|---|
| `list_jobs` | `read:jobs` | 전체 Job 목록 |
| `get_job(job_id)` | `read:jobs` | Job 상세 |
| `list_runs({job_id?, status?, limit?})` | `read:runs` | Run 이력 조회 (최신순, `limit` 기본 20·최대 200). 각 항목은 Agent 스키마 — "마지막 성공 Run의 출력값"은 `list_runs(job_id=…, status="SUCCESS", limit=1)` |
| `get_run(run_id)` | `read:runs` | Run 상태/결과 (Agent 스키마 — `params`·`outputs` 포함) |
| `get_run_logs(run_id, step_id, {tail?})` | `read:runs` | Step 로그 텍스트 (`tail` 기본 200줄) |
| `subscribe_run(run_id, {tail?})` | `read:runs` | 이 MCP 서버 프로세스의 log_bus 최근 이벤트 스냅샷 (스트리밍 아님) |
| `upload_artifact(name, version, content_base64, {ext?})` | `write:uploads` | 아티팩트 업로드 (base64 인코딩) |
| `get_artifact(name, version)` | `read:jobs` | 아티팩트 상태. `version`에 `latest` 사용 가능 |
| `run_job(job_id, {mode, artifact_refs?, params?, idempotency_key?})` | `run:<job_id>` | Run 트리거. `mode`: `sync` / `async`. `artifact_refs`는 `{alias: "uploads://<name>@<ver\|latest>"}`, 생략한 alias는 `@latest`로 해석 후 구체 버전으로 고정. `params`는 `{name: value}`로 Job이 선언한 파라미터만 허용하며, 생략한 파라미터는 기본값 ([Run 파라미터](./run-params.md)). 선언 내용은 `get_job`의 `params`로 확인 |
| `cancel_run(run_id)` | 그 Run의 `run:<job_id>` | 실행 중 Run 취소 |

`list_jobs`/`get_job` 응답에는 Job 정의 전체(`steps[].env` 포함)가 담깁니다 — [Security](./security.md#3-secret_-환경변수)의 주의 사항을 참고하세요.

### 4.1 오류 응답

인증·rate-limit 단계의 실패만 HTTP 상태로 돌아옵니다.

| HTTP | 본문 | 상황 |
|---|---|---|
| `401` | `{"error": "UNAUTH", "detail": "missing bearer" \| "invalid key" \| "expired key"}` | Bearer 누락 · 일치하는 ACTIVE Key 없음(revoke 포함) · 만료 |
| `429` | `{"error": "RATE_LIMIT", "retry_after": N}` + `Retry-After` 헤더 | Key의 분당 호출 수 초과 |

그 외 실패는 HTTP 200의 JSON-RPC 응답 안에서 **tool 오류**(`isError: true`)로 돌아오며, 텍스트가 `<CODE>: <설명>` 형태입니다.

| 코드 | 상황 |
|---|---|
| `DENY` | Key scope 미매칭 (`auth.fail` audit 기록) |
| `NOT_FOUND` | job/run/artifact/로그 없음 |
| `CONFLICT` | 같은 Job이 이미 실행 중(`… already running as #<run_id>`) · 다른 Job이 쓴 `idempotency_key` · 같은 `name@version` 아티팩트 존재 |
| `NOT_RUNNING` | `cancel_run` 대상이 실행 중이 아님 |
| `UNKNOWN_ALIAS` / `MISMATCH` / `INVALID_ARTIFACT` / `NOT_READY` | 아티팩트 참조 해석 실패 ([Artifacts §5](./artifacts.md#5-오류-코드)) |
| `UNKNOWN_PARAM` / `INVALID_PARAM` | 파라미터 해석 실패 ([Run 파라미터 §4](./run-params.md#4-오류-코드)) |

참조·파라미터 해석 실패로 거부된 트리거는 Run을 만들지 않고 `mcp.run`(result=DENY) audit을 남깁니다.

## 5. 실행 모드

- **`sync`** (기본): Run 완료까지 대기 후 Agent 스키마로 응답. `TASKFLOW_MCP_MAX_SYNC_SEC`(기본 600초) 초과 시 `{run_id, status:"RUNNING", degraded_to:"async"}` 반환
- **`async`**: 즉시 `{run_id, status:"RUNNING", poll_url}` 반환 → 이후 `get_run(run_id)`로 polling

Run은 호출을 받은 MCP 서버 프로세스 안에서 실행됩니다. 실시간 이벤트는 그 프로세스에만 있으므로 MCP로 트리거한 Run은 Backend의 `GET /api/runs/{id}/stream`(SSE)으로 받을 수 없습니다 — 진행 상황은 `get_run` polling이나 `subscribe_run`으로 확인하세요.

## 6. Idempotency

`run_job` 호출에 `idempotency_key`를 전달하면 동일 키로 재호출 시 새 Run을 만들지 않고 **기존 Run을 반환**합니다 (DB의 `Run.idempotency_key` unique index). 키에는 만료가 없으므로, 같은 키는 기간과 무관하게 항상 처음 Run을 가리킵니다. 재호출 시의 `artifact_refs`·`params`는 무시됩니다.
키는 테이블 전체에서 유일하므로 **Job마다 다른 키를 써야 합니다.** 다른 Job에서 같은 키를 재사용하면 그 Job의 run이 반환되는 대신 `CONFLICT`로 거부됩니다.

## 7. Claude Desktop 연결

Claude Desktop 최신 버전은 HTTP MCP transport를 지원합니다. 설정 파일 위치는 배포본에 따라 다릅니다:

- macOS: `~/Library/Application Support/Claude/claude_desktop_config.json`
- Linux/Windows: `~/.config/claude/mcp.json` 계열

```json
{
  "mcpServers": {
    "taskflow": {
      "url": "http://localhost:7391/mcp",
      "headers": {
        "Authorization": "Bearer mcp_tk_live_..."
      }
    }
  }
}
```

Claude Desktop 재시작 후 채팅에서 `list_jobs` 등의 도구가 노출됩니다.

> 일부 Claude Desktop 배포본은 stdio transport만 지원합니다. 그 경우 별도 브릿지 프로세스를 작성하거나, 공식 MCP 클라이언트 라이브러리(`@modelcontextprotocol/sdk`, `mcp` Python)를 사용해 직접 연결하세요.

## 트러블슈팅

MCP 관련 오류는 [Troubleshooting](./troubleshooting.md)의 MCP 섹션 참조.
