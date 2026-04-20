# TaskFlow MCP Server

**AI Agent가 1차 사용자인 Workflow 오케스트레이션 플랫폼.** Scope 기반 권한, argv allowlist, hash-chained audit으로 Agent 실행을 통제하며, MCP(Model Context Protocol) 엔드포인트를 통해 Claude 등 Agent가 Job을 안전하게 실행할 수 있게 한다.

> 설계 문서: [`docs/00-overview.md`](./docs/00-overview.md) → [`01-design-goals.md`](./docs/01-design-goals.md) → [`02-business-rules.md`](./docs/02-business-rules.md) → [`03-system-spec.md`](./docs/03-system-spec.md) 순서로 읽기를 권장.

---

## 목차

1. [특징](#특징)
2. [아키텍처](#아키텍처)
3. [요구사항](#요구사항)
4. [설치](#설치)
5. [실행](#실행)
6. [첫 번째 Job 만들기 (UI)](#첫-번째-job-만들기-ui)
7. [MCP 세팅](#mcp-세팅)
8. [Claude Desktop 연결](#claude-desktop-연결)
9. [API 참조](#api-참조)
10. [보안 정책](#보안-정책)
11. [주요 명령](#주요-명령)
12. [테스트](#테스트)
13. [트러블슈팅](#트러블슈팅)
14. [범위에서 제외](#범위에서-제외)

---

## 특징

- **AI Agent First** — MCP 엔드포인트로 Agent가 Job을 직접 트리거, 결과는 구조화된 Agent 스키마(`status`, `steps[]`, `failed_step`, `err_message`, `logs_uri`, `audit_event_ids`)로 반환
- **Sandboxed by default** — `shell=False`(argv 리스트 전용), argv allowlist, 고정 cwd, 시크릿 환경변수 마스킹
- **Observable** — SSE로 실시간 stdout/stderr 스트림, Workflow DAG 시각화(DAG · List · Timeline 3뷰)
- **Immutable audit** — append-only hash-chained 감사 로그, `/api/audit/verify`로 무결성 검증
- **MCP 통제** — Key별 scope(`run:<job-id>` / `read:*` / `write:uploads` 등) + 토큰 버킷 rate-limit + 발급/회전/revoke 전체 감사 기록
- **빈 DB로 시작** — 프로토타입 더미 데이터 없음. 사용자가 UI/MCP로 실제 Job/Key/Artifact를 생성

## 아키텍처

```
┌─────────────────────────────────────────────────────────┐
│  Frontend  (Vite + React + TS)      :5173              │
│  ├─ Dashboard · Builder · Monitor · Logs ...            │
│  └─ zustand store + EventSource(SSE)                    │
└────────────────────────┬────────────────────────────────┘
                         │ HTTP (proxied)
┌────────────────────────▼────────────────────────────────┐
│  FastAPI Backend  :8000                                 │
│  ├─ /api/jobs · /api/runs · /api/artifacts ...          │
│  ├─ /api/runs/{id}/stream  (SSE)                        │
│  └─ asyncio Run Engine ─► subprocess_exec (shell=False) │
├─────────────────────────────────────────────────────────┤
│  MCP Server  :7391  (mcp-python-sdk, streamable-http)   │
│  └─ Bearer middleware → 10 tools (list_jobs, run_job…)  │
├─────────────────────────────────────────────────────────┤
│  SQLite (taskflow.db) + 로컬 FS (storage/)              │
│  └─ jobs · runs · run_steps · artifacts · audit · keys  │
└─────────────────────────────────────────────────────────┘
```

| 구성 요소 | 위치 |
|---|---|
| Backend API · MCP 서버 | `backend/app/` (FastAPI · SQLAlchemy async · mcp>=1.27) |
| Run 엔진 · Worker | `backend/app/engine/` (asyncio, `create_subprocess_exec`) |
| 정책 (allowlist · shell=False) | `backend/app/engine/policies.py` · `backend/app/dev/allowlist.yaml` |
| DB 마이그레이션 | `backend/alembic/versions/` |
| Frontend | `frontend/src/` (React · TypeScript · zustand) |
| 설계 문서 | `docs/00-…03-*.md` |
| 런타임 데이터 | `backend/taskflow.db`, `backend/storage/` (gitignore) |

---

## 요구사항

- **Python 3.11 이상** (3.14에서도 검증됨)
- **Node.js 20 이상**, `npm` 10 이상
- macOS · Linux (Windows는 WSL 권장)

## 설치

### 1. 저장소 클론 후 `.env` 준비 (선택)

```sh
git clone <this-repo> taskflow-mcp-server
cd taskflow-mcp-server
cp .env.example .env          # 기본값이 적절하므로 보통 수정 불필요
```

### 2. 의존성 설치 + DB 마이그레이션

```sh
make setup
```

`make setup`이 수행하는 일:

1. `backend/.venv` 파이썬 가상환경 생성
2. `pip install -e "backend[dev]"` 로 FastAPI · SQLAlchemy · `mcp` SDK · pytest 등 설치
3. `cd frontend && npm install` 로 React 등 프론트엔드 의존성 설치
4. `alembic upgrade head` 로 `backend/taskflow.db` 스키마 생성

빈 DB로 시작한다. seed 데이터는 투입되지 않는다.

## 실행

```sh
make dev
```

3개 프로세스가 동시에 뜬다:

| 프로세스 | 포트 | 역할 |
|---|---|---|
| Backend | `http://localhost:8000` | REST API · SSE |
| MCP Server | `http://localhost:7391/mcp` | MCP 엔드포인트 (Bearer 인증) |
| Frontend | `http://localhost:5173` | React UI (API는 Vite 프록시) |

**첫 실행 시** Backend가 admin 세션 토큰을 한 번 콘솔에 출력한다. 지금은 UI 로그인이 활성화되지 않아 바로 UI를 쓸 수 있지만, 토큰은 향후 UI 인증 활성화 시를 위해 기록해 두는 편을 권장한다.

브라우저에서 http://localhost:5173 을 열면 **"등록된 Job이 없습니다"** 빈 상태가 보인다.

> **IPv4 바인딩 주의**: Vite 기본 설정은 `localhost`에만 바인드한다. `curl http://127.0.0.1:5173`은 실패할 수 있으니 `curl http://localhost:5173`을 쓰라.

---

## 첫 번째 Job 만들기 (UI)

1. Dashboard → `+ 새 Job`
2. Builder에서 다음을 입력
   - **ID**: `hello` (kebab-case, 소문자)
   - **Name**: `Hello Demo`
   - **Step 1**: argv = `["echo", "hello from taskflow"]`, timeout = 10
   - **Step 2**: argv = `["sleep", "1"]`, deps = `greet`, timeout = 5
3. `저장` → Dashboard로 이동
4. `hello` 행의 `▷ 실행` 클릭
5. Topbar에 `LIVE` 칩 표시 → Monitor 화면에서 실제 stdout이 SSE로 스트림됨
6. 완료 후 Audit 화면에서 `job.create`, `job.run`, `job.run.done` 이벤트 확인 가능

**중요:** Step의 argv는 `backend/app/dev/allowlist.yaml`에 등록된 커맨드만 사용할 수 있다. 기본 허용:

```yaml
allow:
  - ["echo"]
  - ["printf"]
  - ["sleep"]
  - ["ls"]
  - ["cat"]
  - ["/bin/true"]
  - ["/bin/false"]
  # + /bin/*, /usr/bin/* variants
```

자신의 환경에서 필요한 커맨드(예: `npm`, `aws`)는 이 파일에 명시적으로 추가해야 실행된다. 이는 사고 방지를 위한 의도된 제한이다.

---

## MCP 세팅

TaskFlow MCP 서버는 **Streamable HTTP transport**로 동작한다. 모든 호출은 `Authorization: Bearer <token>` 헤더가 필요하다.

### 1) MCP Key 발급

UI: `MCP Key` 화면 → `+ 새 Key 발급` → Label / Scope / 만료일 / Rate limit 선택 → **Key는 발급 직후 단 1회만 화면에 표시**됨. 안전하게 복사해둘 것.

CLI로도 발급 가능:

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

`plaintext` 값을 **이 순간 한 번만** 얻을 수 있다. DB에는 hash만 저장된다.

### Scope 규칙

| Scope | 의미 |
|---|---|
| `read:jobs` / `read:runs` / `read:*` | 조회 도구만 허용 |
| `run:<job-id>` | 특정 Job 실행 |
| `run:*` | 모든 Job 실행 |
| `write:uploads` | 아티팩트 업로드 |

매칭 우선순위 (docs/02 §7.3): `run:<job-id>` > `run:*` > read-only. Read-only Key로는 `run_job` 불가 → `403 DENY` + `auth.fail` audit.

### 2) MCP 프로토콜로 직접 호출

MCP는 JSON-RPC 2.0 기반이며 `initialize` → `notifications/initialized` → `tools/call` 순서로 진행한다.

```sh
TOKEN="mcp_tk_live_...(발급받은 plaintext)..."

# 1. initialize
curl -D /tmp/hdr -X POST http://localhost:7391/mcp \
  -H "Content-Type: application/json" \
  -H "Accept: application/json, text/event-stream" \
  -H "Authorization: Bearer $TOKEN" \
  -d '{"jsonrpc":"2.0","id":1,"method":"initialize","params":{
       "protocolVersion":"2025-06-18","capabilities":{},
       "clientInfo":{"name":"curl","version":"1"}}}'

# 응답 헤더에서 Mcp-Session-Id 추출 (이후 모든 호출에 필수)
SESSION=$(grep -i "mcp-session-id:" /tmp/hdr | awk '{print $2}' | tr -d '\r')

# 2. 초기화 알림
curl -X POST http://localhost:7391/mcp \
  -H "Content-Type: application/json" \
  -H "Accept: application/json, text/event-stream" \
  -H "Authorization: Bearer $TOKEN" \
  -H "Mcp-Session-Id: $SESSION" \
  -d '{"jsonrpc":"2.0","method":"notifications/initialized","params":{}}'

# 3. 사용 가능한 도구 목록
curl -X POST http://localhost:7391/mcp \
  -H "Content-Type: application/json" \
  -H "Accept: application/json, text/event-stream" \
  -H "Authorization: Bearer $TOKEN" \
  -H "Mcp-Session-Id: $SESSION" \
  -d '{"jsonrpc":"2.0","id":2,"method":"tools/list","params":{}}'

# 4. run_job (sync 모드)
curl -X POST http://localhost:7391/mcp \
  -H "Content-Type: application/json" \
  -H "Accept: application/json, text/event-stream" \
  -H "Authorization: Bearer $TOKEN" \
  -H "Mcp-Session-Id: $SESSION" \
  -d '{"jsonrpc":"2.0","id":3,"method":"tools/call","params":{
       "name":"run_job",
       "arguments":{"job_id":"hello","mode":"sync"}}}'
```

`run_job(mode=sync)` 응답은 Run이 종료될 때까지 블로킹되며, Body의 `content[0].text`에 다음 JSON이 담긴다 (docs/02 §10.4):

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

동시에 `audit` 테이블에 `mcp.run` (src=mcp), `job.run.done` 이벤트가 기록된다.

### 3) MCP 도구 목록

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

### 4) 실행 모드

- **`sync`** (기본): Run 완료까지 대기 후 Agent 스키마로 응답. `MCP_MAX_SYNC_SEC`(기본 600초) 초과 시 `{run_id, status:"RUNNING", degraded_to:"async"}` 반환
- **`async`**: 즉시 `{run_id}` 반환 → 이후 `get_run(run_id)`로 polling

### 5) Idempotency

`run_job` 호출에 `idempotency_key`를 전달하면 동일 키로 재호출 시 **기존 run_id를 반환**한다 (DB의 `Run.idempotency_key` unique index).

---

## Claude Desktop 연결

Claude Desktop 최신 버전은 HTTP MCP transport를 지원한다. `~/.config/claude/mcp.json` (macOS의 경우 `~/Library/Application Support/Claude/claude_desktop_config.json` 계열 경로를 쓰는 배포본도 있음):

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

Claude Desktop 재시작 후 채팅에서 `list_jobs` 등의 도구가 노출된다.

> 일부 Claude Desktop 배포본은 stdio transport만 지원한다. 그 경우 별도 브릿지 프로세스를 작성하거나, 공식 MCP 클라이언트 라이브러리(`@modelcontextprotocol/sdk`, `mcp` Python)를 사용해 직접 연결하라.

---

## API 참조

### REST (Backend `:8000`)

| Method · Path | 설명 |
|---|---|
| `GET /api/health` | 헬스체크 |
| `GET /api/jobs` | Job 목록 |
| `GET /api/jobs/{id}` | Job 상세 |
| `POST /api/jobs` | Job 생성 |
| `PATCH /api/jobs/{id}` | Job 수정 |
| `DELETE /api/jobs/{id}` | Job 삭제 |
| `POST /api/jobs/{id}/runs` | Run 트리거 (body: `{trigger, actor, idempotency_key?}`) |
| `GET /api/runs?job_id=&status=&limit=` | Run 이력 |
| `GET /api/runs/{id}` | Run 단건 (`steps[]` 포함) |
| `POST /api/runs/{id}/cancel` | Run 취소 |
| `GET /api/runs/{id}/stream` | SSE — `run.started` / `step.started` / `step.log` / `step.finished` / `run.finished` |
| `GET /api/artifacts` | 아티팩트 목록 |
| `POST /api/artifacts` | multipart 업로드 (`name`, `version`, `ext`, `uploader`, `file`) |
| `GET /api/audit?kind=&result=&q=&limit=` | 감사 이벤트 조회 |
| `GET /api/audit/verify` | hash-chain 무결성 검증 |
| `GET /api/audit/export.csv` | CSV 내보내기 |
| `GET /api/keys` | MCP Key 목록 |
| `POST /api/keys` | Key 발급 (plaintext 1회 노출) |
| `DELETE /api/keys/{id}` | Key revoke |

### SSE 이벤트 포맷 (docs/03 §2.4)

```
event: run.started     data: {run_id, job_id, at}
event: step.started    data: {step_id, cmd, timeout}
event: step.log        data: {step_id, ts, lvl, text}
event: step.finished   data: {step_id, state, elapsed_sec}
event: run.finished    data: {run_id, status, failed_step, err_message, duration_sec}
event: ping            data: {}            # 30초마다 heartbeat
```

### 오류 코드 (docs/03 §2.5)

| HTTP | 의미 |
|---|---|
| `400 INVALID_ARTIFACT` | 해시/형식 불일치 |
| `401 UNAUTH` | Bearer 누락/유효하지 않은 key |
| `403 DENY` | scope 미매칭 |
| `404 NOT_FOUND` | job/run/artifact 없음 |
| `409 CONFLICT` | 동시성 차단 (`current_run_id` 포함) |
| `429 RATE_LIMIT` | rate-limit 초과 (`retry_after` 포함) |
| `202 SCANNING` | 아티팩트 스캔 중 |

Job 자체의 `FAILED`/`TIMEOUT`은 HTTP 에러가 아니라 응답 body의 `status` 필드로 전달된다.

---

## 보안 정책

강제되는 정책:

- **`shell=False`** — `asyncio.create_subprocess_exec(*argv)` 전용. shell 문자열 실행 경로가 코드에 부재.
- **argv allowlist** — `backend/app/dev/allowlist.yaml` 미매칭 시 `policy.violation` audit + DENY.
- **고정 cwd** — `./storage/runtime` (env `TASKFLOW_STEP_CWD`로 override).
- **시크릿 마스킹** — `SECRET_*` prefix의 환경변수는 로그 마스킹 + `secret.read` audit.
- **Hash-chained audit** — 모든 감사 이벤트는 `prev_hash` + `sha256(canonical_body)` 체인. `GET /api/audit/verify`로 tamper detection.
- **MCP Key 보호** — DB에는 hash만 저장. 발급 시 plaintext 1회 노출. scope 매칭 + 토큰 버킷 rate-limit. 발급/회전/revoke 모두 audit 기록.

---

## 주요 명령

| 상황 | 명령 | 비고 |
|---|---|---|
| 최초 설치 | `make setup` | venv · npm · migrate |
| 로컬 dev | `make dev` | Vite는 `localhost`만 바인드 (같은 머신에서만 접근) |
| LAN dev | `make dev-lan` | Vite·API·MCP 모두 `0.0.0.0`으로 바인드 |
| 프로덕션 빌드 | `make build` | `frontend/dist` 생성 |
| 프로덕션 실행 | `make start` | backend가 SPA+API 통합 서빙, MCP 분리 |
| 테스트 | `make test` | pytest 16개 |
| DB 초기화 | `make reset` | SQLite + storage 삭제 후 migrate |
| 전체 제거 | `make clean` | venv / node_modules / DB |

개별 서비스:

```sh
make dev-backend   # uvicorn app.main:app :8000 (dev)
make dev-mcp       # python -m app.mcp_server :7391 (dev)
make dev-frontend  # vite :5173 (dev)
make start-backend # production: SPA+API 통합
make start-mcp     # production MCP
```

## 네트워크 바인딩

기본 `make dev`는 **개발자 로컬에서만** 접근 가능하도록 Vite를 `localhost`에 바인드합니다. 원격 호스트(같은 LAN 내 다른 기기 등)에서 쓰려면:

```sh
# 1) LAN 바인딩으로 실행
make dev-lan TASKFLOW_CORS_ORIGINS=http://192.168.1.10:5173

# 2) 또는 환경변수로 세밀 제어
TASKFLOW_FRONTEND_HOST=0.0.0.0 \
TASKFLOW_API_HOST=0.0.0.0 \
TASKFLOW_MCP_HOST=0.0.0.0 \
TASKFLOW_API_HOST_PUBLIC=192.168.1.10 \
TASKFLOW_CORS_ORIGINS=http://192.168.1.10:5173 \
  make dev
```

- `TASKFLOW_FRONTEND_HOST` — Vite 바인딩 인터페이스
- `TASKFLOW_API_HOST` / `TASKFLOW_MCP_HOST` — FastAPI / MCP 바인딩 인터페이스
- `TASKFLOW_API_HOST_PUBLIC` — 브라우저/외부 클라이언트가 API에 접근할 때 쓰는 호스트 (Vite proxy target 구성용)
- `TASKFLOW_CORS_ORIGINS` — **콤마 구분** origin 화이트리스트. 원격 브라우저가 `/api`를 직접 호출할 때 반드시 포함. Vite 프록시 경유 호출은 same-origin이라 CORS 영향 없음. dev에서 `*` 한 개만 넣으면 allow-all.

**주의:** UI에는 현재 로그인 게이트가 없습니다. `dev-lan`으로 외부 노출 시 누구나 Job 생성/실행이 가능하므로 신뢰된 네트워크에서만 사용하세요.

## 프로덕션 릴리즈

`make start`는 다음을 수행합니다:

1. Backend(uvicorn) 한 포트에서 **API + 빌드된 SPA**를 동시 서빙 — 별도 Vite 프로세스 불필요, CORS 이슈 자연 제거 (same-origin).
2. MCP 서버는 기존처럼 7391 포트에서 독립 실행.
3. `TASKFLOW_ENV=production`으로 설정되어 CORS가 `TASKFLOW_CORS_ORIGINS`에 지정된 항목으로 고정됨 (`*`는 안전을 위해 production에서 자동 제거).

릴리즈 파이프라인 예:

```sh
# 1) 빌드
make build                       # frontend/dist 생성

# 2) 환경 설정 (.env 예시)
# TASKFLOW_ENV=production
# TASKFLOW_API_PORT=80
# TASKFLOW_MCP_PORT=7391
# TASKFLOW_CORS_ORIGINS=https://taskflow.example.com
# TASKFLOW_FRONTEND_DIST_DIR=../frontend/dist

# 3) 실행 (필요시 systemd / pm2 / Docker 등에 래핑)
make start API_PORT=80

# 또는 수동으로
TASKFLOW_ENV=production \
TASKFLOW_FRONTEND_DIST_DIR=../frontend/dist \
  ./backend/.venv/bin/uvicorn app.main:app --host 0.0.0.0 --port 80

TASKFLOW_ENV=production \
  ./backend/.venv/bin/python -m app.mcp_server
```

리버스 프록시(Nginx/Caddy)를 쓰는 경우 `/`와 `/api/*`를 backend 포트로, `/mcp`를 MCP 포트로 각각 프록시하면 됩니다. HTTPS 종단도 리버스 프록시 계층에서 처리하는 것을 권장.

### 환경변수 참조

| 변수 | 기본값 | 설명 |
|---|---|---|
| `TASKFLOW_ENV` | `dev` | `dev` \| `production` |
| `TASKFLOW_DB_URL` | `sqlite+aiosqlite:///./taskflow.db` | DB URL |
| `TASKFLOW_STORAGE_DIR` | `./storage` | 아티팩트·로그 루트 |
| `TASKFLOW_STEP_CWD` | `./storage/runtime` | Step subprocess cwd |
| `TASKFLOW_API_HOST` / `TASKFLOW_API_PORT` | `0.0.0.0` / `8000` | Backend 바인딩 |
| `TASKFLOW_MCP_HOST` / `TASKFLOW_MCP_PORT` | `0.0.0.0` / `7391` | MCP 바인딩 |
| `TASKFLOW_MCP_MAX_SYNC_SEC` | `600` | `run_job(sync)` 최대 대기 |
| `TASKFLOW_FRONTEND_HOST` / `TASKFLOW_FRONTEND_PORT` | `localhost` / `5173` | Vite 바인딩 |
| `TASKFLOW_API_HOST_PUBLIC` | `localhost` | 외부에서 본 API 호스트 (Vite proxy target) |
| `TASKFLOW_CORS_ORIGINS` | `http://localhost:5173,http://127.0.0.1:5173` | 콤마 구분 origin 화이트리스트 |
| `TASKFLOW_FRONTEND_DIST_DIR` | *(unset)* | production 모드의 SPA dist 경로 |

---

## 테스트

```sh
make test
```

pytest 16개 케이스:

- `test_audit_chain.py` — 10개 이벤트 체인 intact, 1 row 위변조 탐지
- `test_dag.py` — topo sort, 비순환 검증, 중복 id/shell 문자열 거부
- `test_allowlist.py` — `echo` 허용, `rm` 거부, 비-리스트 argv 거부
- `test_scope.py` — 정확 매칭 / wildcard / read-only가 run 거부
- `test_rate_limit.py` — 10/min 버스트 후 11번째 호출 시 `retry_after`

---

## 트러블슈팅

### Python 3.14에서 `greenlet` 누락 에러

```
ValueError: the greenlet library is required to use this function.
```

해결:

```sh
backend/.venv/bin/pip install "greenlet>=3.0"
```

`backend/pyproject.toml`에 이미 명시되어 있으므로 `make setup` 재실행으로도 해결된다.

### `curl http://127.0.0.1:5173`이 실패

Vite 기본 dev 서버는 `localhost` (IPv6 우선)만 바인드한다. `curl http://localhost:5173/` 를 쓰거나 `vite.config.ts`에 `server.host = '0.0.0.0'` 을 추가하라.

### MCP 호출이 `400 Bad Request`로 실패

모든 MCP 호출(최초 `initialize` 제외)은 `Mcp-Session-Id` 헤더를 요구한다. `initialize` 응답 헤더에서 값을 추출해 이후 호출에 포함시킬 것.

또한 `Accept: application/json, text/event-stream` 헤더가 필요하다.

### allowlist에 없는 커맨드로 Job 실행이 즉시 `policy.violation`

의도된 동작이다. `backend/app/dev/allowlist.yaml`에 해당 argv 프리픽스를 추가하고 backend를 재시작하라.

```yaml
allow:
  - ["npm", "ci"]
  - ["npm", "run", "build"]
  - ["aws", "s3", "sync"]
```

### Run이 `RUNNING`에서 진행되지 않음

Backend 로그에서 `Task exception was never retrieved`를 확인하라. 대부분 대상 커맨드가 존재하지 않거나 allowlist 미매칭이다. `backend/storage/logs/<run_id>/<step_id>.log` 파일에 stderr가 저장된다.

### Audit chain verify가 FAIL

DB row가 수동으로 변조되었거나 timezone 처리 버그일 수 있다. `GET /api/audit/verify`가 `FAIL: broken at id=N`을 반환하면 N번째 이벤트부터 체인이 깨진 것이다. 정상 운영 상태라면 절대 발생하지 않는다.

---

## 범위에서 제외

docs/00 §5.2 Out-of-scope 기준. 다음은 구현하지 않았고 현재 스프린트 범위 밖이다:

- 복잡한 RBAC/ABAC UI, multi-workspace / multi-tenant
- Workflow GitOps import/export
- 알림 채널 구성 (Step의 notify argv로 대체)
- 분산 Worker 스케줄러 (in-process, 동시성 1)
- ClamAV 실제 연동 (현재 stub — 업로드 즉시 READY)
- SIEM forward 파이프라인 (로컬 audit만)
- 실 `ROLLBACK` 정책 (MVP는 `STOP`으로 수렴)
- PostgreSQL / S3 전환 (Alembic 경로만 열려있음)
- `stream` 모드의 MCP `run_job` (REST SSE 대체 사용)

## 라이선스

내부 프로젝트 (미정).
