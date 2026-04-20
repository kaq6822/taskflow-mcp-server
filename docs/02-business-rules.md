# 비즈니스 룰 (Business Rules)

## 1. 도메인 핵심 개념

| 개념 | 정의 |
|---|---|
| **Job** | 하나의 Workflow 정의. 여러 Step의 DAG + 실행 정책(스케줄/동시성/타임아웃/실패 처리)으로 구성. |
| **Step** | Job 안의 실행 단위. `argv` 배열 명령어 + 타임아웃 + 의존성(`deps`) + 실패 정책. |
| **Run** | Job을 특정 시점에 실행한 인스턴스. 상태 · 로그 · 소요시간 · 트리거 · 실행자 포함. |
| **Trigger** | Run을 발생시킨 주체. `manual` / `schedule`(cron) / `mcp`(AI Agent) 중 하나. |
| **Artifact** | Job Step이 소비하는 배포 산출물. 버전 · 해시 · 서명 · 소비 Job 메타 포함. |
| **Audit Event** | TaskFlow에서 발생한 모든 사용자·시스템 행위의 불변(append-only) 기록. |
| **MCP Key** | AI Agent가 TaskFlow에 인증하기 위한 토큰. scope · 만료 · rate-limit 내장. |

## 2. Job 규칙

### 2.1 Job 식별 · 메타데이터

- Job은 고유 `id`(`deploy-web` 같은 kebab-case) + `name`(한국어 설명) 조합.
- `owner`(계정 또는 bot), `tags`(자유 라벨) 필수.
- `desc`는 Job 상세 화면의 설명 카드에 그대로 노출.

### 2.2 실행 정책

- **`schedule`:** `manual` 또는 cron expression(`0 3 * * *`, `0 9 * * MON` 등).
- **`timeout`(초):** Job 전체 timeout. 이를 초과하면 Run은 `TIMEOUT` 상태로 종료.
- **`concurrency`:** 동시에 몇 개의 Run을 허용할지. 현재 프로토타입은 **항상 1** (동시에 한 Run만, 있을 시 실행 거부 + toast 에러).
- **`onFailure`:** Job 레벨 실패 정책. 값: `STOP` / `CONTINUE` / `RETRY` / `ROLLBACK`.

### 2.3 Step 규칙

- `id`는 Job 내 **고유**. Workflow Builder 검증에서 "모든 step id 고유" 체크.
- `cmd`는 **반드시 argv 배열** (shell injection 방지, `shell=False` 강제). 문자열 단일 명령은 금지.
- `deps`는 같은 Job 내의 다른 step id 배열. **비순환(DAG)**이어야 함.
- `timeout`은 Step 레벨이며 Job `timeout`과 독립.
- `onFailure`: `STOP` / `CONTINUE` / `RETRY` / `ROLLBACK` 중 하나. Step이 실패했을 때 Run이 어떻게 진행될지 결정.

### 2.4 DAG 배치 규칙

- 레벨(level)은 topo sort 기반: deps가 없는 Step은 level 0, 이후는 `max(deps.level) + 1`.
- 같은 level의 Step은 화면에서 **같은 컬럼**에 세로로 배치. 컬럼 간격 160px, 행 간격 60px.

## 3. Run 상태 전이

### 3.1 상태 정의

| 상태 | 의미 | 표시 색 |
|---|---|---|
| `PENDING` | 아직 실행 전 (Step 내부 상태에서만 사용) | 회색 `ink-4` |
| `RUNNING` | 실행 중 | info 파란색 + pulse |
| `SUCCESS` | 모든 Step이 exit 0로 완료 | ok 초록색 |
| `FAILED` | 한 Step 이상이 exit ≠ 0 또는 사용자 취소 | err 빨간색 |
| `TIMEOUT` | Step이 `timeout`초 초과 | warn 주황색 |
| `SKIPPED` | 앞선 Step 실패로 실행되지 않음 | ink-4 · opacity 0.5 |

### 3.2 Run Lifecycle

```
(trigger) → RUNNING (ticks per step) → SUCCESS | FAILED | TIMEOUT
                                    └─ (cancel) → FAILED (err='사용자 취소')
```

- Run 시작 시: 새 `id` = `max(기존 runs의 id) + 1`.
- `order`는 Step의 `topoSort` 결과. Run은 `order[currentIdx]`를 순차 소비.
- 각 Step의 실행 시간은 시뮬레이터에서 `stepTargetDur(step)`으로 결정 (2~6초, step id별 고정 매핑).

### 3.3 Run 실행 제약

- **동시성 1:** 현재 `liveRun`이 있으면 새 Run 시작은 거부 + `이미 실행 중인 Run이 있습니다` toast(err).
- **Cancel:** `cancelRun()`은 `liveRun`을 `FAILED`로 종료. 실패 지점은 `order[currentIdx]`, err 메시지는 `사용자 취소`.

### 3.4 Step 상태 전이 (Run 내부)

```
PENDING → RUNNING → SUCCESS (exit 0)
                  → FAILED (exit ≠ 0, err 기록)
                  → TIMEOUT (elapsed > step.timeout)
                  → SKIPPED (앞 step이 STOP으로 실패)
```

- `RUNNING` 진입 시 `$ <cmd>` 로그 1줄 + `cwd=/srv/app · timeout=Xs · shell=False` 메타 로그 자동 기록.
- 완료 시 `✓ done (X.Xs · exit 0)` 로그.

## 4. 트리거 규칙

- `manual`: 사용자가 UI에서 ▷ 실행 버튼 클릭.
- `schedule`: cron 엔진이 발화 (by=`cron`).
- `mcp`: MCP Key를 통한 AI Agent 호출 (by=`agent/claude` 등).

모든 트리거는 Run 생성 시 **감사 로그에 자동 기록**:

```
{ who: actor, kind: 'job.run', target: `${jobId} #${runId}`, src: trigger === 'mcp' ? 'mcp' : 'web', r: 'OK' }
```

## 5. Artifact 규칙

### 5.1 Artifact 시나리오 범위

파일 업로드 기능은 **오직 "배포 아티팩트" 시나리오**에 한정 (채팅 합의):

- 빌드 산출물(.tar.gz, .jar, .zip, .ipa 등)을 업로드.
- 특정 Job이 해당 아티팩트를 **소비(consume)** — 다운로드 후 서버 배포/전송.
- "어떤 Job이 이 아티팩트를 소비하는가"가 UI의 핵심 맥락.

> 입력 데이터(CSV/JSON) 전달, 설정 파일 주입, 템플릿 리소스 등은 **이 시스템의 scope 밖**이며 외부 스토리지 경로(S3 등) + `params`로 처리.

### 5.2 Artifact 속성

- `name`: 논리적 이름(`web-dist`, `api-server`). 여러 버전이 같은 name을 공유.
- `ver`: semver(`v1.24.3`).
- `ext`: 확장자(`tar.gz`, `jar`, `zip`, `ipa`).
- `size`: MB 단위.
- `sha`: SHA-256 해시 (축약 표시: `c3f92a4e…8b21d4`).
- `by`: 업로더(CI 또는 사용자 계정).
- `at`: 업로드 시각 (relative: `10분 전`, `어제`).
- `latest`: boolean — 동일 name 중 최신인지.
- `consumers`: 이 아티팩트를 사용하는 Job id 배열.
- `status`: `READY` / `SCANNING` — 스캔 완료 전은 소비 불가.

### 5.3 Artifact 참조 규칙

- Step은 환경변수 `$ARTIFACT`에 `uploads://<name>@<ver|latest>` 참조를 받는다.
- 예: `aws s3 sync $ARTIFACT s3://prod-web/`
- `uploads://web-dist@latest`는 항상 `latest=true`인 버전을 가리킴.

### 5.4 Artifact 검증 규칙

아티팩트는 다음 4개 체크를 모두 통과해야 `READY`:

1. MIME / 확장자 일치
2. SHA-256 서명 검증 (CI key)
3. 악성 패턴 스캔 (ClamAV)
4. 실행 권한 제거 · 읽기 전용 mount

### 5.5 Retention

- 보관 정책: **90일** + 마지막 배포에서 참조되는 버전은 유지(Garbage collection 예외).

## 6. Audit 규칙

### 6.1 불변성 원칙

- Audit log는 **append-only**이며 **immutable ledger**.
- 각 이벤트는 hash-chained로 연결되어 **tamper-evident**. 수정 시도는 체인 검증으로 탐지.
- 보관 기간: **30일** (이후 SIEM으로 forwarding).

### 6.2 이벤트 Kind 분류

| Kind | 의미 | 발생 시점 |
|---|---|---|
| `job.run` | Run 시작 | 모든 trigger에서 `startRun()` |
| `job.run.fail` | Run 실패 | FAILED/TIMEOUT 종료 시 |
| `job.triggered` | Scheduler가 Job 발화 | cron 발동 시 |
| `job.create` | 새 Job 생성 | Builder에서 저장 |
| `job.edit` | Job 수정 | Builder에서 저장 |
| `mcp.run` | MCP를 통한 Job 실행 | trigger=mcp인 Run |
| `mcp.key.issue` | 새 Key 발급 | MCP Key Modal 완료 |
| `mcp.key.revoke` | Key revoke | revoke 버튼 |
| `artifact.upload` | 아티팩트 업로드 | Artifacts 화면의 업로드 |
| `auth.fail` | 인증 실패 | 로그인/Key 검증 실패 |
| `secret.read` | 시크릿 접근 | 환경변수 resolve 시 |
| `policy.violation` | 정책 위반 시도 | `shell=True` 시도 등 |

### 6.3 Result Code

- `OK`: 성공적으로 완료.
- `DENY`: 정책/권한에 의해 거부됨.
- `FAIL`: 실행은 시작됐으나 실패함.

### 6.4 필터링/정렬

- Time 기준 내림차순(최신이 위).
- 필터: kind · result · 자유검색(actor/target/kind 부분일치).
- Export: CSV · JSON.

## 7. MCP Key 규칙

### 7.1 Key 상태

| 상태 | 의미 | 가능한 전이 |
|---|---|---|
| `ACTIVE` | 정상 사용 가능 | → `EXPIRING` → `REVOKED` |
| `EXPIRING` | 만료 7일 이내 (자동 분류) | → `ACTIVE`(회전) / `REVOKED` |
| `REVOKED` | 무효화됨. 영구 불가 | (종단) |

### 7.2 Key 발급 규칙

- **Label** 필수 (예: `claude · 운영`, `internal-bot`).
- **Scopes** 체크박스 선택. 현재 제공되는 scope:
  - `read:jobs` / `read:runs` / `read:*`
  - `run:<job-id>` — 특정 Job 실행 권한
  - `write:uploads` — 아티팩트 업로드
- **만료 기간**: 30일 / 90일 / 180일.
- **Rate limit**: 10/min / 30/min / 60/min.
- 발급 완료 시 **Key 값은 단 한 번만 화면에 표시**. 저장 후에는 `mcp_tk_live_XXXX••••••••YYYY` 형태로만 보임.

### 7.3 Key 사용 규칙

- 모든 MCP 호출은 `Bearer <key>` 헤더로 인증.
- Scope 검사: 요청한 Job id가 `run:<job-id>` 또는 `run:*`에 매칭되지 않으면 **DENY** + audit `auth.fail`.
- Rate limit 초과 시 429 + audit 기록.

### 7.4 Key 운영 규칙

- `회전`: 기존 Key를 revoke하고 **같은 label/scope/rate로 새 Key 발급**. (프로토타입에서는 button stub)
- `revoke`: 즉시 `REVOKED`로 전환. scope는 `[]`로 리셋. 이후 호출은 전부 DENY.
- Revoke는 취소 불가. 새 Key를 발급해야 함.

## 8. 보안 정책

### 8.1 Step 실행 환경 (고정)

모든 Step은 다음 정책이 **강제됨** (변경 불가):

- `shell=False` — subprocess shell 미사용, argv 기반.
- `user=taskflow` — 전용 저권한 계정.
- `cwd=/srv/app` — 고정 작업 디렉토리.
- `no-root` — root 권한 실행 금지.
- **Allowlist**: argv 기반 허용 리스트 (화이트리스트). 외부에서 들어온 임의 cmd는 거부.

### 8.2 시크릿 처리

- 환경변수 KEY/VALUE 중 `source=secret`으로 표시된 값은 로그에 `*****`로 마스킹.
- 시크릿 읽기는 `secret.read` audit 이벤트로 기록.

## 9. 오류 진단 규칙 (Heuristic)

로그 뷰어에서 FAILED/TIMEOUT Run이 선택되면 **오류 진단 카드**가 자동 노출:

- **TIMEOUT 케이스:**
  - "Step이 X초 timeout을 초과"
  - 원인 후보: DB lock, 외부 API 응답 지연, 리소스 부족
  - 최근 30일 동일 step timeout 횟수 표시
- **FAILED 케이스:**
  - 원본 에러 메시지 강조
  - 구성 문제(.npmrc 레지스트리 설정 등) 가능성 제시
  - 최근 14일 동일 에러 횟수로 플레이크 여부 판단

### 9.1 복구 액션

- `from failed 재실행`: 실패 지점부터만 재실행 (이전 SUCCESS step skip).
- `전체 재실행`: 처음부터.
- `✎ Step 편집`: 해당 Step을 Builder에서 열기.

## 10. AI Agent End-to-End 플로우 (MCP)

TaskFlow의 1차 유즈케이스. "개발자 ↔ AI Agent ↔ TaskFlow" 삼자 사이의 계약을 정의한다.

### 10.1 표준 시퀀스

```
Developer                AI Agent              TaskFlow MCP             Worker
    │                        │                       │                     │
    │── /deploy ────────────▶│                       │                     │
    │                        │                       │                     │
    │                        │── build (local) ──┐   │                     │
    │                        │◀──────────────────┘   │                     │
    │                        │                       │                     │
    │                        │── upload_artifact ───▶│ (scope:write:uploads)│
    │                        │      (name, ver,file) │                     │
    │                        │◀── {artifact_id,sha}──│                     │
    │                        │                       │                     │
    │                        │── run_job ───────────▶│ (scope:run:<job-id>)│
    │                        │   (job_id, mode,      │                     │
    │                        │    artifact_ref)      │                     │
    │                        │                       │── dispatch ────────▶│
    │                        │                       │                     │
    │                        │                       │◀── step logs ───────│
    │                        │                       │                     │
    │                        │◀── result{status,…} ──│ (sync 모드)        │
    │                        │    ─or─               │                     │
    │                        │◀── {run_id}           │ (async 모드 시 즉시)│
    │                        │   → poll/stream 후    │                     │
    │                        │     result 수신       │                     │
    │                        │                       │                     │
    │◀── 성공/실패 피드백 ───│                       │                     │
```

### 10.2 플로우 단계별 규칙

#### Step 1: 빌드 (Agent 로컬)

- Agent의 `/deploy` skill command가 로컬에서 빌드 실행.
- **TaskFlow는 빌드 자체에 관여하지 않음.** 빌드 산출물만 업로드 대상으로 받음.
- 빌드 실패는 Agent가 자체 처리하며, TaskFlow audit에 기록되지 않음.

#### Step 2: 아티팩트 업로드

- 필수 scope: `write:uploads`.
- 호출: `upload_artifact(name, version, file, [ext], [metadata])`.
- 성공 시 응답: `{ artifact_id, name, version, sha256, status }`
  - `status === 'SCANNING'`이면 아직 소비 불가 — Agent는 `get_artifact(artifact_id)` polling 또는 `run_job`에 전달 시 서버가 READY 대기 후 실행.
- 업로드는 다음 검증을 통과해야 `READY`:
  1. MIME/확장자 일치
  2. SHA-256 서명 검증
  3. 악성 패턴 스캔 (ClamAV)
  4. 실행 권한 제거 · 읽기 전용 전환
- 감사 이벤트: `artifact.upload` · `src=mcp` · `target=<name>@<version>`.

#### Step 3: Job 실행

- 필수 scope: `run:<job-id>` 또는 `run:*`.
- 호출: `run_job(job_id, { mode, artifact_ref?, params?, actor? })`
  - `mode`: `'sync' | 'async' | 'stream'` (§10.3 참고).
  - `artifact_ref`: 사용할 아티팩트의 `uploads://<name>@<ver|latest>` 참조 (Job의 `consumesArtifact`와 일치해야 함).
  - `params`: Job 정의에서 허용된 key만 통과 (unknown key는 DENY).
- scope 검증 실패 시 **DENY + audit `auth.fail`** — Run은 생성되지 않음.
- 동시성 검사: 해당 Job에 `liveRun`이 있으면 거부(429 또는 409) + 기존 run_id 반환.
- Run 생성 시 audit `mcp.run` · `who=<key.label>` · `target=<job_id> #<run_id>`.

#### Step 4: 결과 대기

Agent는 선택한 실행 모드에 따라 결과를 수신(§10.3).

#### Step 5: 개발자에게 피드백

- Agent는 서버가 돌려준 **구조화된 결과**(§10.4)를 자연어로 요약해 개발자에게 전달.
- 실패 시 Agent는 `failed_step`, `err_message`, `logs_uri`를 함께 전달해 개발자가 추가 조치를 취할 수 있게 한다.

### 10.3 실행 모드 (Run Mode) 계약

| 모드 | 반환 시점 | 적합한 상황 |
|---|---|---|
| `sync` | Run이 `SUCCESS/FAILED/TIMEOUT`로 종료될 때까지 blocking | 짧은 Job (≤ 수 분). Agent가 대기 가능 · 개발자에게 즉시 결과 피드백 |
| `async` | `run_id`만 즉시 반환 후 종료 | 긴 Job (ETL, 대용량 배포). Agent는 이후 polling/webhook으로 완료 확인 |
| `stream` | 연결 유지 후 step 단위 이벤트 푸시 (WebSocket/SSE) | Agent가 진행률을 실시간 보고해야 할 때 |

#### sync 모드 제약

- 서버 응답 타임아웃은 `min(job.timeout + buffer, MCP_MAX_SYNC)` — 기본 `MCP_MAX_SYNC = 600s`.
- 초과 시 서버는 자동으로 async로 downgrade하며 `{run_id, degraded_to: 'async'}` 반환.

#### async 모드 후속 호출

- `get_run(run_id)` → `{status, failed_step?, err_message?}`
- `get_run_logs(run_id, step_id)` → 텍스트 로그 (또는 tail=N).
- `subscribe_run(run_id)` (WebSocket) → stream 모드와 동일한 이벤트.

#### stream 모드 이벤트 스키마

```
event: run.started   data: { run_id, job_id, at }
event: step.started  data: { step_id, cmd, timeout }
event: step.log      data: { step_id, ts, lvl, text }
event: step.finished data: { step_id, state, elapsed }
event: run.finished  data: { status, failed_step?, err_message?, duration_sec }
```

### 10.4 Agent용 표준 응답 스키마

`run_job(sync)` 완료 응답 또는 `get_run()` 응답:

```json
{
  "run_id": 4821,
  "job_id": "deploy-web",
  "status": "SUCCESS | FAILED | TIMEOUT",
  "started_at": "2026-04-20T10:12:03Z",
  "finished_at": "2026-04-20T10:16:15Z",
  "duration_sec": 252,
  "artifact_ref": "uploads://web-dist@v1.24.3",
  "steps": [
    { "id": "pull",       "state": "SUCCESS", "elapsed_sec": 2.1 },
    { "id": "fetch-deps", "state": "SUCCESS", "elapsed_sec": 3.8 },
    { "id": "build",      "state": "FAILED",  "elapsed_sec": 5.2 }
  ],
  "failed_step": "build",
  "err_message": "webpack build failed: module not found …",
  "logs_uri": "taskflow://runs/4821/logs",
  "audit_event_ids": [91234, 91235]
}
```

- Agent는 `status` 단일 필드로 1차 분기하고, `FAILED/TIMEOUT`일 때 `failed_step` + `err_message`를 사용자에게 전달.
- `logs_uri`는 MCP의 `get_run_logs(run_id, step_id)` 툴로 바로 호환.

### 10.5 Foreground vs Background (클라이언트 관점)

| 모드 | Agent 측 | 사용자 체감 |
|---|---|---|
| **Foreground** | `run_job(mode=sync)` — 완료까지 현재 turn 유지 | 개발자는 Agent가 "작업 중…" 상태로 대기 · 결과 즉시 수신 |
| **Background** | `run_job(mode=async)` 후 agent가 바로 turn 종료 · 이후 `get_run()` 폴링/webhook으로 완료 수신 | 개발자는 다른 작업 가능 · 완료 시 agent가 별도 알림 메시지 전달 |

서버는 모드 결정에 개입하지 않는다 — **Agent가 개발자 의도에 따라 선택**.

단, 서버는 `job.expected_duration_sec`(Job 정의에 선택적)을 응답에 포함시켜 Agent가 모드를 자동 결정할 수 있도록 힌트를 준다.

### 10.6 실패/예외 규칙

| 상황 | 서버 응답 | Agent 행동 |
|---|---|---|
| scope 미매칭 | `403 DENY` + audit `auth.fail` | 개발자에게 권한 부족 전달 · Key 재발급 제안 |
| rate-limit 초과 | `429` + `retry_after` | backoff 후 재시도 (최대 2회) |
| 동시성 차단 | `409` + `current_run_id` | 진행 중 Run 완료 대기 또는 사용자 확인 |
| artifact SCANNING | `202` + `retry_after` | 지수 backoff 후 재호출 |
| artifact sha256 mismatch | `400 INVALID_ARTIFACT` | 빌드 재시도 · 업로드 재실행 |
| sync 타임아웃 초과 | `200` + `{degraded_to:'async', run_id}` | async 모드로 전환 후 polling |
| Job FAILED | `200` + `status=FAILED` (HTTP 에러 아님) | 결과 스키마의 `failed_step`/`err_message` 피드백 |

**중요:** Job 자체의 실패는 HTTP 에러가 아니라 **응답 body의 `status` 필드**로 전달한다. HTTP 에러는 **프로토콜 레벨 실패**에만 사용.

### 10.7 Idempotency

- Agent가 같은 배포를 중복 트리거하지 않도록 `run_job` 호출에 선택적 `idempotency_key`를 지원.
- 동일 `idempotency_key`로 24시간 내 재호출 시 **새 Run을 만들지 않고** 기존 `run_id`를 반환.

