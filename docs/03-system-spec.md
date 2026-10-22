# 시스템 스펙 (System Specification)

본 문서는 **제품 요구로서의 시스템 스펙**을 다룬다. 구체적 구현 스택·프레임워크·디렉터리 구조는 포함하지 않는다.

## 1. 아키텍처 개요

### 1.1 계층 구조

```
┌──────────────────────────────────────────────┐
│  Web UI                                       │
└──────────────────────────────────────────────┘
                    │
┌──────────────────────────────────────────────┐
│  API Server                                   │
│  - Auth (세션 · MCP Bearer)                   │
│  - Job / Run / Artifact / Audit / Key         │
│  - Live log stream                            │
└──────────────────────────────────────────────┘
                    │
┌──────────────────────────────────────────────┐
│  MCP Endpoint                                 │
│  - Bearer 인증 · scope 검사                   │
│  - rate-limit                                 │
│  - tool exposure                              │
└──────────────────────────────────────────────┘
                    │
┌──────────────────────────────────────────────┐
│  Scheduler (cron)                             │
└──────────────────────────────────────────────┘
                    │
┌──────────────────────────────────────────────┐
│  Worker Pool                                  │
│  - Step 실행 (subprocess, shell=False)        │
│  - stdout/stderr 수집                         │
│  - artifact 읽기 전용 mount                   │
│  - policy enforcement (cwd control)           │
└──────────────────────────────────────────────┘
                    │
┌──────────────────────────────────────────────┐
│  Storage                                      │
│  - 관계형 DB (jobs, runs, audit, keys)        │
│  - Blob (artifacts, 해시 인덱스)              │
│  - Log files (stdout/stderr/combined)         │
└──────────────────────────────────────────────┘
```

### 1.2 주요 시스템 컴포넌트

| 컴포넌트 | 역할 |
|---|---|
| **API** | HTTP 요청 처리 · 인증 · 인가 |
| **Worker** | Step 실행 · 정책 강제 |
| **Queue** | Run 대기열 · 동시성 제어 |
| **DB** | Job · Run · Audit · Key 영속화 |
| **Blob** | Artifact 저장 (해시 인덱스 · 읽기 전용 mount) |
| **MCP** | AI Agent 엔드포인트 (Bearer · scope · rate-limit) |
| **Scheduler** | cron 기반 Job 발화 |

> **구현 현황:** 현재는 API 서버(REST·SSE)와 MCP 엔드포인트가 **별도 프로세스**이며, 각자 asyncio Run Engine을 내장하고 같은 SQLite DB와 `storage/`를 공유합니다. MCP 호출은 API 서버를 거치지 않고 MCP 프로세스 안에서 Run을 실행합니다. Scheduler·Queue·Worker pool은 미구현이고, Web UI 세션 인증(§4.1)도 없습니다.

## 2. MCP 인터페이스

### 2.1 MCP Tools

MCP 서버는 다음 툴을 노출한다. 호출 규칙·응답 스키마·실패 처리는 [`02-business-rules.md §10`](./02-business-rules.md) AI Agent End-to-End 플로우와 일체.

| Tool | 필요 Scope | 모드 | 설명 |
|---|---|---|---|
| `list_jobs()` | `read:jobs` | sync | Job 목록 |
| `get_job(job_id)` | `read:jobs` | sync | Job 단건 정의 |
| `list_runs({job_id?, status?, limit?})` | `read:runs` | sync | Run 이력 조회 |
| `get_run(run_id)` | `read:runs` | sync | Run 상태/결과 단건 (async 모드 polling용) |
| `get_run_logs(run_id, step_id, {tail?})` | `read:runs` | sync | Step 로그 텍스트 |
| `subscribe_run(run_id)` | `read:runs` | stream | step 이벤트 수신 |
| `upload_artifact(name, version, file, {ext?, metadata?})` | `write:uploads` | sync | 배포 아티팩트 업로드 |
| `get_artifact(name, version)` | `read:jobs` | sync | 아티팩트 상태(READY/SCANNING) 조회 |
| `run_job(job_id, {mode, artifact_refs?, params?, idempotency_key?})` | `run:<job_id>` | sync / async / stream | Job 실행 — 모드별 동작은 `02 §10.3` |
| `cancel_run(run_id)` | `run:<job_id>` | sync | 진행 중 Run 취소 |

> **구현 현황:** `upload_artifact`의 실제 인자는 `(name, version, content_base64, ext?)`이며 `metadata`는 없습니다. `run_job`의 `mode`는 `sync`/`async`만, `subscribe_run(run_id, tail?)`은 스트림이 아니라 최근 이벤트 스냅샷을 반환하는 sync tool입니다. 현재 동작은 [MCP API §4](./mcp-api.md#4-도구-목록)가 기준입니다.

### 2.2 실행 대기 계약 (run_job 모드별)

| Mode | HTTP 상태 | 반환 시점 | 응답 본문 |
|---|---|---|---|
| `sync` | 200 | Run 종료 시점 | 전체 결과 (§2.3 스키마) |
| `sync` (timeout 초과) | 200 | `MCP_MAX_SYNC`(기본 600s) 도달 | `{ run_id, status: 'RUNNING', degraded_to: 'async' }` |
| `async` | 202 | 즉시 | `{ run_id, status: 'RUNNING', poll_url }` |
| `stream` | 101 (Upgrade) | 연결 수립 시점 | step 이벤트 (§2.4) |

> **구현 현황:** MCP 응답은 모드와 무관하게 HTTP 200의 JSON-RPC 응답이며, 위 본문은 tool 결과(`content[0].text`)에 담깁니다. `stream` 모드는 미구현입니다.

### 2.3 Agent 응답 스키마 (sync / get_run)

```json
{
  "run_id": 4821,
  "job_id": "deploy-web",
  "status": "SUCCESS | FAILED | TIMEOUT | RUNNING",
  "started_at": "ISO-8601",
  "finished_at": "ISO-8601 | null",
  "duration_sec": 252,
  "artifact_refs": {
    "dist": { "ref": "uploads://web-dist@v1.24.3", "sha256": "a9f3…" }
  },
  "params": { "branch": "release/1.24" },
  "outputs": { "commit": "9535057…" },
  "steps": [
    { "id": "pull", "state": "SUCCESS", "elapsed_sec": 2.1 }
  ],
  "failed_step": "build | null",
  "err_message": "string | null",
  "logs_uri": "taskflow://runs/{run_id}/logs",
  "audit_event_ids": [91234]
}
```

> **구현 현황:** `audit_event_ids`는 응답에 포함되지 않습니다. `list_runs`·`cancel_run`도 같은 스키마를 반환합니다.

### 2.4 Stream 이벤트 포맷

```
event: run.started     data: { run_id, job_id, at, artifacts, params }
event: step.started    data: { step_id, cmd, timeout }
event: step.log        data: { step_id, ts, lvl, text }
event: step.finished   data: { step_id, state, elapsed_sec }
event: run.finished    data: { run_id, status, failed_step?, err_message?, duration_sec }
```

> **구현 현황:** 이 이벤트는 MCP `stream` 모드가 아니라 REST SSE(`GET /api/runs/{id}/stream`)로 제공되며, Run을 실행한 프로세스 안에서만 발행됩니다 — MCP로 트리거한 Run의 이벤트는 REST SSE로 받을 수 없습니다.

### 2.5 MCP 오류 응답

| HTTP | 의미 | 상황 |
|---|---|---|
| 400 `INVALID_ARTIFACT` | 참조를 쓸 수 없음 | `uploads://<name>@<ver>` 파싱 실패 · alias에 빈 참조 전달 · 같은 alias 중복 전달 |
| 400 `UNKNOWN_ALIAS` | Job이 선언하지 않은 alias | `artifact_refs` 키가 `consumesArtifacts`에 없음 |
| 400 `MISMATCH` | alias와 다른 아티팩트 | 참조가 선언된 name과 다른 아티팩트를 가리킴 |
| 400 `INVALID_PARAM` | 파라미터 값을 쓸 수 없음 | 기본값 없는 파라미터 누락 · `pattern` 불일치 · 문자열 아님 · 같은 이름 중복 전달 |
| 400 `UNKNOWN_PARAM` | Job이 선언하지 않은 파라미터 | `params` 키가 Job의 `params` 선언에 없음 |
| 409 `NOT_READY` | 스캔 미완료 | 아티팩트 `status != READY` |
| 401 `UNAUTH` | Bearer 누락/유효하지 않은 key | Key 검증 실패 |
| 403 `DENY` | scope 미매칭 | `run:<job_id>` 없음 |
| 404 `NOT_FOUND` | job/run/artifact 없음 | |
| 409 `CONFLICT` | 동시성 차단 | `current_run_id` 포함 |
| 429 `RATE_LIMIT` | rate-limit 초과 | `retry_after` 포함 |
| 202 `SCANNING` | 아티팩트 스캔 중 | `retry_after` 포함 |

Job 자체의 FAILED/TIMEOUT은 HTTP 에러가 아닌 **응답 body의 `status`**로 전달한다.

> **구현 현황:** MCP 경로에서 HTTP 상태로 오는 것은 `401 UNAUTH`와 `429 RATE_LIMIT`뿐입니다. 나머지 코드(`DENY`·`NOT_FOUND`·`CONFLICT`·`NOT_RUNNING`·아티팩트·파라미터 오류)는 HTTP 200 JSON-RPC 응답 안의 tool 오류 텍스트 `<CODE>: <설명>`로 반환됩니다. `202 SCANNING`은 미구현입니다(스캔 stub, `READY`가 아니면 `NOT_READY`). 위 HTTP 상태 매핑은 REST `POST /api/jobs/{id}/runs`에 적용됩니다 — [REST API](./rest-api.md#오류-코드), [MCP API §4.1](./mcp-api.md#41-오류-응답).

## 3. 성능 · 확장성 요구

| 요구 | 지표 |
|---|---|
| Run 시작 응답 | < 150ms |
| Live 로그 latency | < 500ms (push 간격) |
| 동시 Run 수 | Job별 `concurrency` 제한 (기본 1), 전체 Worker capacity에 따름 |
| Audit 쓰기 | append-only · 이벤트당 단일 트랜잭션 · SIEM forward는 별도 큐 |

## 4. 보안 스펙

### 4.1 인증

- Web UI: 세션 기반 쿠키 (HttpOnly · Secure · SameSite=Lax).
- MCP Endpoint: `Authorization: Bearer <key>`.
- 실패 시 `auth.fail` 이벤트 기록.

### 4.2 인가 (Authorization)

- Scope 기반 (RBAC 아님). Key별로 scope 배열 설정.
- `run:<job-id>`는 해당 Job에 대해서만 유효. `run:*`는 모든 Job.
- 매칭 우선순위: `run:<job-id>` > `run:*` > read-only scope.

> **구현 현황:** Web UI 세션 인증과 REST API 인증은 미구현입니다(`/api/*` 무인증). scope는 MCP 경로에만 적용되며, 요구 scope와 정확히 같거나 같은 네임스페이스의 `<ns>:*`를 가지면 허용합니다.

### 4.3 Worker 정책 (enforced)

- `shell=False`, 제어된 `cwd`(`TASKFLOW_STEP_CWD` 기본 + Step별 `cwd`).
- `user=<전용 저권한>`·`no-root`는 설계 목표이며 **아직 미구현** — Step은 백엔드를 실행한 계정 권한으로 동작한다.
- 실행 가능한 명령 자체는 제한하지 않음. Job 작성 API에 인증이 없으므로 실질적 차단선은 네트워크 접근 제어이며, MCP Key scope는 MCP 경로(실행·조회·업로드)에만 적용됨.
- `cd`, `pushd`, `popd` 같은 shell/process 상태 변경 명령은 거부. 작업 디렉토리는 Step `cwd`로 지정.
- Step 출력 assertion(`success_contains`, `failure_contains`)은 stdout/stderr 스트림을 라인 단위로 관찰해 최종 Step 상태에 반영.
- 네트워크 egress 제어는 **미구현** — 방화벽/seccomp 등 OS 계층에 위임한다. Step은 백엔드 호스트의 네트워크에 그대로 접근한다.

### 4.4 감사 무결성

- Audit row는 `prev_hash` + `content_hash`로 체인 연결.
- 정기적 체인 검증. 불일치 시 알람.
- SIEM forward는 TLS 보호 채널.

> **구현 현황:** 체인 검증은 `GET /api/audit/verify` 수동 호출로만 이루어지며, 정기 검증·알람·SIEM forward는 미구현입니다.

## 5. 운영 요구

### 5.1 모니터링 대상

- API 응답 시간 · 에러율
- Worker 상태 · Step 평균 실행 시간
- MCP 호출량 · 실패율
- Audit ingest lag · 체인 검증 상태

### 5.2 백업

- DB: 일일 스냅샷 → 장기 보관 스토리지.
- Artifacts: 90일 retention + 마지막 배포 참조는 보존.
- Audit: 30일 로컬 보관 + SIEM으로 영구 보관 이관.

### 5.3 장애 처리

- Worker 다운: 다른 Worker로 재배치. Run은 `FAILED`로 닫고 운영자가 재실행 결정.
- 실행 중 Run에 Worker crash: `TIMEOUT`으로 표기하고 실패 진단 제공.
- API 다운: 쓰기 차단. 읽기는 캐시 데이터로 유지 가능.
