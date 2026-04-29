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
│  - policy enforcement (allowlist, no-root)    │
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
| `run_job(job_id, {mode, artifact_ref?, params?, idempotency_key?})` | `run:<job_id>` | sync / async / stream | Job 실행 — 모드별 동작은 `02 §10.3` |
| `cancel_run(run_id)` | `run:<job_id>` | sync | 진행 중 Run 취소 |

### 2.2 실행 대기 계약 (run_job 모드별)

| Mode | HTTP 상태 | 반환 시점 | 응답 본문 |
|---|---|---|---|
| `sync` | 200 | Run 종료 시점 | 전체 결과 (§2.3 스키마) |
| `sync` (timeout 초과) | 200 | `MCP_MAX_SYNC`(기본 600s) 도달 | `{ run_id, status: 'RUNNING', degraded_to: 'async' }` |
| `async` | 202 | 즉시 | `{ run_id, status: 'RUNNING', poll_url }` |
| `stream` | 101 (Upgrade) | 연결 수립 시점 | step 이벤트 (§2.4) |

### 2.3 Agent 응답 스키마 (sync / get_run)

```json
{
  "run_id": 4821,
  "job_id": "deploy-web",
  "status": "SUCCESS | FAILED | TIMEOUT | RUNNING",
  "started_at": "ISO-8601",
  "finished_at": "ISO-8601 | null",
  "duration_sec": 252,
  "artifact_ref": "uploads://web-dist@v1.24.3",
  "steps": [
    { "id": "pull", "state": "SUCCESS", "elapsed_sec": 2.1 }
  ],
  "failed_step": "build | null",
  "err_message": "string | null",
  "logs_uri": "taskflow://runs/{run_id}/logs",
  "audit_event_ids": [91234]
}
```

### 2.4 Stream 이벤트 포맷

```
event: run.started     data: { run_id, job_id, at }
event: step.started    data: { step_id, cmd, timeout }
event: step.log        data: { step_id, ts, lvl, text }
event: step.finished   data: { step_id, state, elapsed_sec }
event: run.finished    data: { status, failed_step?, err_message?, duration_sec }
```

### 2.5 MCP 오류 응답

| HTTP | 의미 | 상황 |
|---|---|---|
| 400 `INVALID_ARTIFACT` | 해시/형식 불일치 | artifact_ref 검증 실패 |
| 401 `UNAUTH` | Bearer 누락/유효하지 않은 key | Key 검증 실패 |
| 403 `DENY` | scope 미매칭 | `run:<job_id>` 없음 |
| 404 `NOT_FOUND` | job/run/artifact 없음 | |
| 409 `CONFLICT` | 동시성 차단 | `current_run_id` 포함 |
| 429 `RATE_LIMIT` | rate-limit 초과 | `retry_after` 포함 |
| 202 `SCANNING` | 아티팩트 스캔 중 | `retry_after` 포함 |

Job 자체의 FAILED/TIMEOUT은 HTTP 에러가 아닌 **응답 body의 `status`**로 전달한다.

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

### 4.3 Worker 정책 (enforced)

- `shell=False`, `user=<전용 저권한>`, 제어된 `cwd`(`TASKFLOW_STEP_CWD` 기본 + Step별 `cwd`), `no-root`.
- Allowlist 기반 argv 실행. 미등록 명령어는 `policy.violation` + DENY.
- `cd`, `pushd`, `popd` 같은 shell/process 상태 변경 명령은 거부. 작업 디렉토리는 Step `cwd`로 지정.
- 네트워크: egress 정책으로 제한된 도메인만 허용.

### 4.4 감사 무결성

- Audit row는 `prev_hash` + `content_hash`로 체인 연결.
- 정기적 체인 검증. 불일치 시 알람.
- SIEM forward는 TLS 보호 채널.

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
