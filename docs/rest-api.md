# REST API

Backend REST API는 `http://localhost:8000`에서 서빙됩니다. Frontend(Vite dev)는 `/api/*`를 이쪽으로 프록시합니다. 프로덕션(`make start`)에서는 Backend가 SPA+API를 같은 포트에서 통합 서빙합니다.

> `/api/*`에는 **인증이 없습니다**. MCP Key·scope는 MCP 서버(`:7391`)에만 적용됩니다. 감사 로그의 `who`는 요청 헤더 `X-Actor`(없으면 `admin`)나 body의 `actor`/`uploader` 값을 그대로 씁니다. 자세한 내용은 [Security](./security.md).

## 엔드포인트

| Method · Path | 설명 |
|---|---|
| `GET /api/health` | 헬스체크 (`{status, env}`) |
| `GET /api/jobs` | Job 목록 (최근 수정순) |
| `GET /api/jobs/{id}` | Job 상세 |
| `POST /api/jobs` | Job 생성 (201). 이미 있는 id면 `409` |
| `PATCH /api/jobs/{id}` | Job 수정. 보낸 필드만 바뀌며 `null` 값은 "보내지 않음"으로 취급 |
| `DELETE /api/jobs/{id}` | Job 삭제 (204). Run 이력도 함께 삭제. 실행 중 Run이 있으면 `409 {error: "CONFLICT", current_run_id}` |
| `POST /api/jobs/{id}/runs` | Run 트리거 (201, 응답은 Run). body: `{trigger?, actor?, artifact_refs?, params?, idempotency_key?}` — `trigger`는 `manual`(기본)/`schedule`/`mcp`, `actor` 기본값 `web`. `artifact_refs`는 `{alias: "uploads://<name>@<ver\|latest>"}`, 생략한 alias는 `@latest`. `params`는 `{name: value}`, 생략한 파라미터는 기본값 ([Run 파라미터](./run-params.md)). 같은 `idempotency_key`로 다시 보내면 기존 Run을 반환 |
| `GET /api/runs?job_id=&status=&limit=` | Run 이력 (최신순, `limit` 기본 50·최대 500). 예: 마지막 성공 Run의 출력값 → `?job_id=…&status=SUCCESS&limit=1` |
| `GET /api/runs/{id}` | Run 단건 (`steps[]`·`params`·`outputs` 포함 — [Run 출력값](./run-outputs.md)) |
| `GET /api/runs/{id}/logs/{step_id}?tail=200` | Step stdout/stderr 로그 tail (`text/plain`, `tail` 1–2000) |
| `POST /api/runs/{id}/cancel` | Run 취소. 실행 중이 아니면 `404` |
| `POST /api/jobs/{id}/runs/cancel` | 해당 Job의 실행 중 Run 취소 |
| `GET /api/runs/{id}/stream` | SSE — `run.started` / `step.started` / `step.log` / `step.finished` / `run.finished` |
| `GET /api/artifacts` | 아티팩트 목록 (최근 업로드순) |
| `GET /api/artifacts/{id}` | 아티팩트 단건 |
| `POST /api/artifacts` | multipart 업로드 (`name`, `version`, `ext`, `uploader`, `file`). 같은 `name@version`이면 `409` |
| `GET /api/audit?kind=&result=&q=&limit=` | 감사 이벤트 조회 |
| `GET /api/audit/verify` | hash-chain 무결성 검증 |
| `GET /api/audit/export.csv` | CSV 내보내기 |
| `GET /api/keys` | MCP Key 목록 |
| `POST /api/keys` | Key 발급 (plaintext 1회 노출) |
| `DELETE /api/keys/{id}` | Key revoke |

## Job 필드

| 필드 | 설명 |
|---|---|
| `id` | 필수. Job 식별자 (생성 후 변경 불가) |
| `name` · `owner` | 필수 |
| `description` · `tags` | 선택 |
| `schedule` | 기본 `manual`. cron 문자열을 저장·표시하지만 **이를 발화하는 스케줄러는 미구현**입니다 |
| `timeout` | 기본 600. **Job 전체 timeout 강제는 미구현** — 실제로는 Step별 `timeout`만 적용됩니다 |
| `concurrency` | 기본 1. 값과 무관하게 Job당 동시 Run은 1개 |
| `on_failure` | Step에 `on_failure`가 없을 때 쓰는 기본값 (`STOP` 기본) |
| `consumes_artifacts` | `[{alias, name}]` — [Artifacts](./artifacts.md) |
| `params` | `[{name, default, pattern}]` — `default: null`이면 필수. [Run 파라미터](./run-params.md) |
| `steps` | 필수. 아래 Step 필드 배열 |

## Job Step 필드

`POST /api/jobs`, `PATCH /api/jobs/{id}`의 `steps[]` 항목은 다음 필드를 사용합니다:

| 필드 | 설명 |
|---|---|
| `id` | Job 안에서 고유한 Step id |
| `cmd` | `shell=False`로 실행되는 argv 배열. 문자열 shell 명령은 거부 |
| `cwd` | 선택. Step 실행 디렉토리. 생략 시 `TASKFLOW_STEP_CWD` 사용 |
| `success_contains` | 선택. exit 0 이후 stdout/stderr에 모두 포함되어야 하는 문자열 배열 |
| `failure_contains` | 선택. stdout/stderr에 하나라도 포함되면 Step을 실패 처리할 문자열 배열 |
| `timeout` | Step timeout 초 (기본 60) |
| `deps` | 선행 Step id 배열 |
| `on_failure` | `STOP` / `CONTINUE` / `RETRY`(1회 재시도) / `ROLLBACK`(현재 `STOP`과 동일) |
| `env` | Step 전용 환경변수. `PARAM_*`·`ARTIFACT_*` 같은 예약 키는 덮어쓸 수 없음 ([Security](./security.md)) |

`cd`, `pushd`, `popd`는 Step 명령으로 사용할 수 없습니다. 작업 디렉토리는 `cwd` 필드로 지정하세요.

`failure_contains`는 exit code보다 우선 적용됩니다. `success_contains`는 프로세스가 exit 0으로 끝난 뒤 검증되며, 지정 문자열 중 하나라도 누락되면 Step은 `FAILED`가 됩니다.

## SSE 이벤트 포맷

```
event: run.started     data: {run_id, job_id, at, artifacts, params}
event: step.started    data: {step_id, cmd, timeout}
event: step.log        data: {step_id, ts, lvl, text}
event: step.finished   data: {step_id, state, elapsed_sec}
event: run.finished    data: {run_id, status, failed_step, err_message, duration_sec}
event: ping            data: {}            # 30초 동안 이벤트가 없으면 heartbeat
```

- `run.started`의 `artifacts`는 `{alias: "uploads://<name>@<version>"}`(고정된 참조), `params`는 Run에 고정된 파라미터 값입니다.
- `step.log`의 `lvl`은 `cmd`(실행 명령) / `dim`(메타: cwd·timeout, `artifacts · …`, `params · …`, `outputs · …` 등) / `info`(stdout) / `err`(stderr·실패) / `warn` / `ok`입니다.
- 구독 시점 이전 이벤트는 프로세스 메모리에 남은 최근 500개까지 먼저 재생되고, `run.finished` 뒤에 스트림이 닫힙니다.
- 이벤트는 Run을 실행하는 프로세스 안에만 있습니다. MCP로 트리거한 Run은 MCP 서버 프로세스에서 실행되므로 이 엔드포인트로는 이벤트가 오지 않습니다(heartbeat만 옴) — `GET /api/runs/{id}`로 polling하세요.

브라우저에서 `EventSource('/api/runs/{id}/stream')`로 바로 구독할 수 있습니다.

## 오류 코드

오류 본문은 FastAPI 형식인 `{"detail": …}`입니다. Run 트리거 거부와 동시성 충돌은 `detail`이 `{"error": "<코드>", …}` 객체이고, 그 밖의 오류는 `detail`이 설명 문자열입니다.

| HTTP | `detail.error` | 의미 |
|---|---|---|
| `400` | `INVALID_ARTIFACT` / `UNKNOWN_ALIAS` / `MISMATCH` | 아티팩트 참조 해석 실패 ([Artifacts §5](./artifacts.md#5-오류-코드)) |
| `400` | `UNKNOWN_PARAM` / `INVALID_PARAM` | 파라미터 해석 실패 ([Run 파라미터 §4](./run-params.md#4-오류-코드)) |
| `404` | `NOT_FOUND` | 참조한 아티팩트 없음 |
| `409` | `NOT_READY` | 아티팩트가 `READY` 아님 |
| `409` | `CONFLICT` | 같은 Job의 Run이 이미 실행 중(`current_run_id` 포함) · 다른 Job이 쓴 `idempotency_key`(`current_run_id: null`) · 실행 중인 Job 삭제 |
| `400` | (문자열) | Job 저장 검증 실패 — DAG(순환·미지 deps·argv 형식), `cd`/`pushd`/`popd`, alias·params 선언 오류 · 업로드 필드 형식 오류 |
| `404` | (문자열) | job/run/step/로그/key 없음, 취소할 실행 중 Run 없음 |
| `409` | (문자열) | 이미 있는 Job id · 이미 있는 아티팩트 `name@version` |
| `422` | (검증 목록) | 요청 body 스키마 불일치 |

거부된 Run 트리거는 Run을 만들지 않고 감사 로그에 `job.run`(result=DENY)으로 남습니다. `401 UNAUTH`·`429 RATE_LIMIT`·`DENY`는 MCP 서버에서만 발생합니다([MCP API §4.1](./mcp-api.md#41-오류-응답)).

Job 자체의 `FAILED`/`TIMEOUT`은 HTTP 에러가 아니라 응답 body의 `status` 필드로 전달됩니다.

## 관련 문서

- MCP를 통한 도구 호출 → [MCP API](./mcp-api.md)
- 포트/바인딩/CORS 설정 → [Operations](./operations.md)
- 보안 모델 → [Security](./security.md)
