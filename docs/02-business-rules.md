# 비즈니스 룰 (Business Rules)

## 1. 도메인 핵심 개념

| 개념 | 정의 |
|---|---|
| **Job** | 하나의 Workflow 정의. 여러 Step의 DAG + 실행 정책(스케줄/동시성/타임아웃/실패 처리)으로 구성. |
| **Step** | Job 안의 실행 단위. `argv` 배열 명령어 + 작업 디렉토리(`cwd`) + 타임아웃 + 의존성(`deps`) + 실패 정책. |
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
- **`params`:** 실행 시점에 받을 값의 선언(`name` · `default` · `pattern`). 규칙은 §10.2 Step 3과 [Run 파라미터](./run-params.md).

> **구현 현황:** `schedule`은 저장·표시만 되며 cron으로 발화하는 스케줄러는 없습니다. Job 전체 `timeout`도 강제되지 않으며 Step별 `timeout`만 적용됩니다. `ROLLBACK`은 `STOP`과 동일하게 동작합니다.

### 2.3 Step 규칙

- `id`는 Job 내 **고유**. Workflow Builder 검증에서 "모든 step id 고유" 체크.
- `cmd`는 **반드시 argv 배열** (shell injection 방지, `shell=False` 강제). 문자열 단일 명령은 금지.
- `cwd`는 선택 필드. 생략 시 `TASKFLOW_STEP_CWD` 기본값(`./storage/runtime`) 사용. 명시하면 해당 디렉토리가 Step subprocess의 작업 디렉토리가 됨.
- `cd`, `pushd`, `popd` 같은 shell/process 상태 변경 명령은 Step 명령으로 금지. 작업 위치 변경은 `cwd`로 표현.
- `success_contains`는 선택 필드. 프로세스가 exit 0으로 끝난 뒤 stdout/stderr에 지정 문자열이 모두 포함되어야 SUCCESS.
- `failure_contains`는 선택 필드. stdout/stderr에 지정 문자열 중 하나라도 포함되면 exit code와 무관하게 FAILED.
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
- 각 Step은 실제 subprocess로 실행되며, 소요 시간은 실측값(`elapsed_sec`)으로 기록된다. (프로토타입의 `stepTargetDur` 시뮬레이션은 구현에 쓰이지 않는다.)

### 3.3 Run 실행 제약

- **동시성 1:** 현재 `liveRun`이 있으면 새 Run 시작은 거부 + `이미 실행 중인 Run이 있습니다` toast(err).
- **Cancel:** `cancelRun(run_id)` 또는 `cancelJobRun(job_id)`은 실행 중 Run을 `FAILED`로 종료. err 메시지는 `사용자 취소`.

### 3.4 Step 상태 전이 (Run 내부)

```
PENDING → RUNNING → SUCCESS (exit 0)
                  → FAILED (exit ≠ 0, err 기록)
                  → FAILED (failure_contains 매칭 또는 success_contains 누락)
                  → TIMEOUT (elapsed > step.timeout)
                  → SKIPPED (앞 step이 STOP으로 실패)
```

- `RUNNING` 진입 시 `$ <cmd>` 로그 1줄 + `cwd=<step.cwd|TASKFLOW_STEP_CWD> · timeout=Xs · shell=False` 메타 로그 자동 기록.
- 출력 assertion이 있으면 `output assertions · success_contains=N · failure_contains=N` 메타 로그 자동 기록.
- 아티팩트·파라미터가 있으면 `artifacts · uploads://…` · `params · PARAM_X=…` 메타 로그, step이 남긴 출력값은 종료 시 `outputs · key=value` 로그로 기록.
- 완료 시 `✓ done (X.Xs · exit 0)` 로그.

## 4. 트리거 규칙

- `manual`: 사용자가 UI에서 ▷ 실행 버튼 클릭.
- `schedule`: cron 엔진이 발화 (by=`cron`).
- `mcp`: MCP Key를 통한 AI Agent 호출 (by=`agent/claude` 등).

모든 트리거는 Run 생성 시 **감사 로그에 자동 기록**:

```
{ who: actor, kind: 'job.run', target: `${jobId} #${runId}`, src: trigger === 'mcp' ? 'mcp' : 'web', r: 'OK' }
```

> **구현 현황:** MCP `run_job`으로 생성된 Run은 kind `mcp.run`으로 기록됩니다. `schedule` 트리거를 발화하는 스케줄러는 없습니다(§2.2).

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

- Job은 `consumesArtifacts`에 `{alias, name}` 목록을 선언한다. alias는 환경변수 이름의 일부가 되므로 `^[A-Za-z][A-Za-z0-9_]*$`로 제한하고, Job 안에서 중복될 수 없다. 아티팩트 이름은 `.`/`-`를 허용하므로 alias를 분리하지 않으면 `my-app`과 `my.app`이 같은 환경변수 키로 충돌한다.
- Run 시작 시 alias마다 참조를 해석하고, Step은 다음 환경변수를 받는다.
  - `ARTIFACT_<ALIAS>_PATH` — 해석된 blob 절대경로
  - `ARTIFACT_<ALIAS>_NAME` · `_VERSION` · `_SHA256` · `_REF`
- `shell=False`이므로 `cmd` argv에는 변수 치환이 일어나지 않는다. 아티팩트 경로를 쓰는 Step은 이 환경변수를 읽는 스크립트를 호출해야 한다.
- 예: `deploy.sh` 내부에서 `install -m 0644 "$ARTIFACT_JAR_PATH" /opt/svc/app.jar`
- `uploads://web-dist@latest`는 해석 시점에 `latest=true`인 버전을 가리킨다. 해석 결과는 구체 버전으로 Run에 고정(pin)되므로, Run 도중 새 업로드가 포인터를 옮겨도 그 Run의 모든 Step은 같은 버전을 본다.
- `ARTIFACT_*` 키는 Step의 `env`로 덮어쓸 수 없다. 덮어쓰기를 시도하면 무시하고 경고를 로그에 남긴다 — 기록된 pin과 실제 배포본이 어긋나지 않게 하기 위함이다.

### 5.4 Artifact 검증 규칙

아티팩트는 다음 4개 체크를 모두 통과해야 `READY`:

1. MIME / 확장자 일치
2. SHA-256 서명 검증 (CI key)
3. 악성 패턴 스캔 (ClamAV)
4. 실행 권한 제거 · 읽기 전용 mount

> **구현 현황:** 업로드 시 SHA-256을 계산해 기록하고 파일을 0444(읽기 전용)로 잠그는 것까지만 구현되어 있습니다. MIME 검사·서명 검증·ClamAV 스캔은 없으며(stub) 업로드 즉시 `READY`가 됩니다.

### 5.5 Retention

- 보관 정책: **90일** + 마지막 배포에서 참조되는 버전은 유지(Garbage collection 예외).

> **구현 현황:** 보관 정책·자동 정리는 미구현입니다. 아티팩트 삭제 API도 없습니다.

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

> **구현 현황:** 현재 기록되는 kind는 `job.create` · `job.edit` · `job.delete` · `job.run` · `job.run.done` · `job.run.fail` · `job.run.cancel` · `mcp.run` · `mcp.key.issue` · `mcp.key.revoke` · `mcp.rate_limit` · `artifact.upload` · `auth.fail` · `policy.violation`입니다. `job.triggered`·`secret.read`는 발생하지 않습니다. 30일 보관·SIEM forward는 미구현이며, 내보내기는 CSV(`GET /api/audit/export.csv`)만 제공합니다.

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

> **구현 현황:** `EXPIRING` 자동 분류와 회전은 미구현입니다. 만료일이 지난 Key는 상태와 무관하게 인증 단계에서 거부됩니다.

### 7.2 Key 발급 규칙

- **Label** 필수 (예: `claude · 운영`, `internal-bot`).
- **Scopes** 체크박스 선택. 현재 제공되는 scope:
  - `read:jobs` / `read:runs` / `read:*`
  - `run:<job-id>` — 특정 Job 실행 권한
  - `write:uploads` — 아티팩트 업로드
- **만료 기간**: 30일 / 90일 / 180일 / 무제한.
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
- `cwd` — 기본은 `TASKFLOW_STEP_CWD`, Step별 `cwd` 지정 가능. `cd`류 상태 변경 명령은 거부.

전용 저권한 계정(`user=taskflow`)과 `no-root` 실행은 설계 목표이나 **아직 강제되지 않는다** — Step은 백엔드를 실행한 계정 권한으로 동작한다.

실행 가능한 명령 자체도 제한하지 않는다. Job을 만들고 편집할 수 있는 권한이 곧 서버에서 임의 명령을 실행할 수 있는 권한이며, Job 작성 API에는 아직 인증이 없으므로 실질적인 차단선은 네트워크 접근 제어다. MCP Key scope는 실행(`run:<job-id>`)·조회·업로드 등 MCP 경로에만 적용된다. 모든 실행은 감사 로그로 추적된다.

### 8.2 시크릿 처리

- 환경변수 KEY/VALUE 중 `source=secret`으로 표시된 값은 로그에 `*****`로 마스킹.
- 시크릿 읽기는 `secret.read` audit 이벤트로 기록.

> **구현 현황:** 값 마스킹과 `secret.read`는 미구현입니다. `SECRET_` 접두 환경변수는 실행 로그에 이름만 표시되고, Step `env` 값은 Job 정의에 평문으로 저장됩니다. Run 파라미터(`PARAM_*`)와 출력값은 로그·Run 기록에 그대로 남으므로 비밀값을 담지 않습니다. 자세한 내용은 [Security §3–4](./security.md).

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

> **구현 현황:** `from failed 재실행`은 미구현이며, 재실행은 항상 처음부터입니다. 파라미터를 선언한 Job은 보고 있던 Run의 파라미터 값으로 입력 창을 엽니다.

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
    │                        │    artifact_refs)     │                     │
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

> **구현 현황:** 실제 시그니처는 `upload_artifact(name, version, content_base64, ext?)`이며 `metadata`는 없습니다. 응답에 `size_bytes`가 추가됩니다. 조회는 `get_artifact(name, version)`(`version`에 `latest` 가능)입니다. 스캔이 stub이라 업로드 즉시 `READY`이고, `READY`가 아닌 아티팩트를 `run_job`에 넘기면 대기하지 않고 `NOT_READY`로 거부합니다.
- 업로드는 다음 검증을 통과해야 `READY`:
  1. MIME/확장자 일치
  2. SHA-256 서명 검증
  3. 악성 패턴 스캔 (ClamAV)
  4. 실행 권한 제거 · 읽기 전용 전환
- 감사 이벤트: `artifact.upload` · `src=mcp` · `target=<name>@<version>`.

#### Step 3: Job 실행

- 필수 scope: `run:<job-id>` 또는 `run:*`.
- 호출: `run_job(job_id, { mode, artifact_refs?, params?, actor? })`
  - `mode`: `'sync' | 'async' | 'stream'` (§10.3 참고).
  - `artifact_refs`: `{alias: 'uploads://<name>@<ver|latest>'}` 맵. 생략한 alias는 `@latest`로 해석된다. alias 키는 대소문자를 구분하지 않는다(`jar` 선언에 `JAR` 전달 가능). Job이 선언하지 않은 alias는 `UNKNOWN_ALIAS`, 참조가 다른 아티팩트를 가리키면 `MISMATCH`로 거부된다. 생략과 달리 **빈 참조를 명시적으로 전달하면** `@latest`로 대체하지 않고 `INVALID_ARTIFACT`로 거부한다.
  - `params`: `{name: value}` 문자열 맵. Job의 `params` 선언에 있는 이름만 통과하고, 선언에 없는 이름은 `UNKNOWN_PARAM`으로 거부한다(대소문자 무시). 생략한 파라미터는 선언의 `default`, `default`가 없으면 `INVALID_PARAM`. `pattern`이 있으면 값 **전체**가 일치해야 하며, 문자열이 아니거나 빈 값·앞뒤 공백·제어문자·유효하지 않은 UTF-8·1024자 초과도 `INVALID_PARAM`. 해석된 전체 값(기본값 포함)은 Run에 고정되고 step은 `PARAM_<NAME>`으로 받는다 — step `env`로 덮어쓸 수 없다.
- scope 검증 실패 시 **DENY + audit `auth.fail`** — Run은 생성되지 않음.
- 동시성 검사: 해당 Job에 `liveRun`이 있으면 거부(429 또는 409) + 기존 run_id 반환.
- Run 생성 시 audit `mcp.run` · `who=<key.label>` · `target=<job_id> #<run_id>`.

> **구현 현황:** 실제 시그니처는 `run_job(job_id, mode?, artifact_refs?, params?, idempotency_key?)`이며 `actor`는 받지 않습니다(Key label이 actor). `mode`는 `sync`/`async`만 지원합니다. 동시성 차단은 tool 오류 `CONFLICT: job <id> already running as #<run_id>`로 반환됩니다(HTTP 상태 아님).

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

> **구현 현황:** `stream` 모드는 미구현입니다. `sync` 대기 상한은 `TASKFLOW_MCP_MAX_SYNC_SEC`(기본 600s)만 적용되며 `job.timeout`은 반영되지 않습니다. `subscribe_run`은 WebSocket이 아니라 공유 log_bus의 최근 이벤트 스냅샷을 돌려주는 일반 tool입니다. polling·webhook 중 webhook은 미구현입니다.

#### sync 모드 제약

- 서버 응답 타임아웃은 `min(job.timeout + buffer, MCP_MAX_SYNC)` — 기본 `MCP_MAX_SYNC = 600s`.
- 초과 시 서버는 자동으로 async로 downgrade하며 `{run_id, degraded_to: 'async'}` 반환.

#### async 모드 후속 호출

- `get_run(run_id)` → `{status, failed_step?, err_message?}`
- `get_run_logs(run_id, step_id)` → 텍스트 로그 (또는 tail=N).
- `subscribe_run(run_id)` (WebSocket) → stream 모드와 동일한 이벤트.

#### stream 모드 이벤트 스키마

```
event: run.started   data: { run_id, job_id, at, artifacts, params }
event: step.started  data: { step_id, cmd, timeout }
event: step.log      data: { step_id, ts, lvl, text }
event: step.finished data: { step_id, state, elapsed_sec }
event: run.finished  data: { run_id, status, failed_step?, err_message?, duration_sec }
```

(같은 이벤트가 REST SSE `GET /api/runs/{id}/stream`으로 제공된다 — [REST API](./rest-api.md#sse-이벤트-포맷).)

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
  "artifact_refs": {
    "dist": { "ref": "uploads://web-dist@v1.24.3", "sha256": "a9f3…" }
  },
  "params": { "branch": "release/1.24" },
  "outputs": {},
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
- `params`는 Run에 고정된 파라미터 값(기본값 포함), `outputs`는 SUCCESS로 끝난 step이 `::output key=value`로 남긴 값([Run 출력값](./run-outputs.md)).

> **구현 현황:** `audit_event_ids`는 응답에 포함되지 않습니다.

### 10.5 Foreground vs Background (클라이언트 관점)

| 모드 | Agent 측 | 사용자 체감 |
|---|---|---|
| **Foreground** | `run_job(mode=sync)` — 완료까지 현재 turn 유지 | 개발자는 Agent가 "작업 중…" 상태로 대기 · 결과 즉시 수신 |
| **Background** | `run_job(mode=async)` 후 agent가 바로 turn 종료 · 이후 `get_run()` 폴링/webhook으로 완료 수신 | 개발자는 다른 작업 가능 · 완료 시 agent가 별도 알림 메시지 전달 |

서버는 모드 결정에 개입하지 않는다 — **Agent가 개발자 의도에 따라 선택**.

단, 서버는 `job.expected_duration_sec`(Job 정의에 선택적)을 응답에 포함시켜 Agent가 모드를 자동 결정할 수 있도록 힌트를 준다. (구현 현황: `expected_duration_sec`은 미구현.)

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

> **구현 현황:** MCP 경로에서 HTTP 상태로 오는 것은 `401 UNAUTH`와 `429 RATE_LIMIT`뿐이고, scope 미매칭(`DENY`)·동시성 차단(`CONFLICT`)·아티팩트/파라미터 해석 실패는 JSON-RPC 응답 안의 tool 오류(`<CODE>: <설명>`)로 돌아옵니다. `SCANNING`(202) 대기 경로는 없고 `READY`가 아닌 아티팩트는 `NOT_READY`로 거부됩니다. 파라미터 오류는 `UNKNOWN_PARAM`·`INVALID_PARAM`. 전체 목록은 [MCP API §4.1](./mcp-api.md#41-오류-응답).

### 10.7 Idempotency

- Agent가 같은 배포를 중복 트리거하지 않도록 `run_job` 호출에 선택적 `idempotency_key`를 지원.
- 동일 `idempotency_key`로 24시간 내 재호출 시 **새 Run을 만들지 않고** 기존 `run_id`를 반환.

> **구현 현황:** 키에 만료가 없어 24시간이 지나도 같은 Run을 반환합니다. 키는 테이블 전체에서 유일하므로 다른 Job에서 같은 키를 쓰면 `CONFLICT`로 거부됩니다.
