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

매칭 우선순위: `run:<job-id>` > `run:*` > read-only. Read-only Key로 `run_job` 호출 시 `403 DENY` + `auth.fail` audit 기록.

## 3. JSON-RPC로 직접 호출

```sh
TOKEN="mcp_tk_live_...(발급받은 plaintext)..."

# 1) initialize
curl -D /tmp/hdr -X POST http://localhost:7391/mcp \
  -H "Content-Type: application/json" \
  -H "Accept: application/json, text/event-stream" \
  -H "Authorization: Bearer $TOKEN" \
  -d '{"jsonrpc":"2.0","id":1,"method":"initialize","params":{
       "protocolVersion":"2025-06-18","capabilities":{},
       "clientInfo":{"name":"curl","version":"1"}}}'

# 응답 헤더에서 Mcp-Session-Id 추출 (이후 모든 호출에 필수)
SESSION=$(grep -i "mcp-session-id:" /tmp/hdr | awk '{print $2}' | tr -d '\r')

# 2) 초기화 알림
curl -X POST http://localhost:7391/mcp \
  -H "Content-Type: application/json" \
  -H "Accept: application/json, text/event-stream" \
  -H "Authorization: Bearer $TOKEN" \
  -H "Mcp-Session-Id: $SESSION" \
  -d '{"jsonrpc":"2.0","method":"notifications/initialized","params":{}}'

# 3) 사용 가능한 도구 목록
curl -X POST http://localhost:7391/mcp \
  -H "Content-Type: application/json" \
  -H "Accept: application/json, text/event-stream" \
  -H "Authorization: Bearer $TOKEN" \
  -H "Mcp-Session-Id: $SESSION" \
  -d '{"jsonrpc":"2.0","id":2,"method":"tools/list","params":{}}'

# 4) run_job (sync 모드)
curl -X POST http://localhost:7391/mcp \
  -H "Content-Type: application/json" \
  -H "Accept: application/json, text/event-stream" \
  -H "Authorization: Bearer $TOKEN" \
  -H "Mcp-Session-Id: $SESSION" \
  -d '{"jsonrpc":"2.0","id":3,"method":"tools/call","params":{
       "name":"run_job",
       "arguments":{"job_id":"hello","mode":"sync"}}}'
```

`run_job(mode=sync)` 응답은 Run이 종료될 때까지 블로킹되며 `content[0].text`에 다음 JSON이 담깁니다:

```json
{
  "run_id": 4821,
  "job_id": "hello",
  "status": "SUCCESS",
  "started_at": "...",
  "finished_at": "...",
  "duration_sec": 1.02,
  "steps": [
    {"id": "greet", "state": "SUCCESS", "elapsed_sec": 0.002},
    {"id": "wait",  "state": "SUCCESS", "elapsed_sec": 1.01}
  ],
  "failed_step": null,
  "err_message": null,
  "logs_uri": "taskflow://runs/4821/logs"
}
```

동시에 `audit` 테이블에 `mcp.run` (src=mcp), `job.run.done` 이벤트가 기록됩니다.

## 4. 도구 목록

| Tool | 필요 Scope | 설명 |
|---|---|---|
| `list_jobs` | `read:jobs` | 전체 Job 목록 |
| `get_job(job_id)` | `read:jobs` | Job 상세 |
| `list_runs({job_id?, status?, limit?})` | `read:runs` | Run 이력 조회 |
| `get_run(run_id)` | `read:runs` | Run 상태/결과 (Agent 스키마) |
| `get_run_logs(run_id, step_id, {tail?})` | `read:runs` | Step 로그 텍스트 |
| `subscribe_run(run_id, {tail?})` | `read:runs` | log_bus 최근 이벤트 스냅샷 |
| `upload_artifact(name, version, content_base64, {ext?})` | `write:uploads` | 아티팩트 업로드 (base64 인코딩) |
| `get_artifact(name, version)` | `read:jobs` | 아티팩트 상태 |
| `run_job(job_id, {mode, artifact_ref?, idempotency_key?})` | `run:<job_id>` | Run 트리거. `mode`: `sync` / `async` |
| `cancel_run(run_id)` | `run:<job_id>` | 실행 중 Run 취소 |

## 5. 실행 모드

- **`sync`** (기본): Run 완료까지 대기 후 Agent 스키마로 응답. `TASKFLOW_MCP_MAX_SYNC_SEC`(기본 600초) 초과 시 `{run_id, status:"RUNNING", degraded_to:"async"}` 반환
- **`async`**: 즉시 `{run_id}` 반환 → 이후 `get_run(run_id)`로 polling

## 6. Idempotency

`run_job` 호출에 `idempotency_key`를 전달하면 동일 키로 재호출 시 **기존 run_id를 반환**합니다 (DB의 `Run.idempotency_key` unique index).

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
