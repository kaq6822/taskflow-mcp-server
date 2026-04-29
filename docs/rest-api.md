# REST API

Backend REST API는 `http://localhost:8000`에서 서빙됩니다. Frontend(Vite dev)는 `/api/*`를 이쪽으로 프록시합니다. 프로덕션(`make start`)에서는 Backend가 SPA+API를 같은 포트에서 통합 서빙합니다.

## 엔드포인트

| Method · Path | 설명 |
|---|---|
| `GET /api/health` | 헬스체크 |
| `GET /api/jobs` | Job 목록 |
| `GET /api/jobs/{id}` | Job 상세 |
| `POST /api/jobs` | Job 생성 |
| `PATCH /api/jobs/{id}` | Job 수정 |
| `DELETE /api/jobs/{id}` | Job 삭제 |
| `POST /api/jobs/{id}/runs` | Run 트리거 (body: `{trigger, actor, artifact_ref?, idempotency_key?}`) |
| `GET /api/runs?job_id=&status=&limit=` | Run 이력 |
| `GET /api/runs/{id}` | Run 단건 (`steps[]` 포함) |
| `POST /api/runs/{id}/cancel` | Run 취소 |
| `POST /api/jobs/{id}/runs/cancel` | 해당 Job의 실행 중 Run 취소 |
| `GET /api/runs/{id}/stream` | SSE — `run.started` / `step.started` / `step.log` / `step.finished` / `run.finished` |
| `GET /api/artifacts` | 아티팩트 목록 |
| `POST /api/artifacts` | multipart 업로드 (`name`, `version`, `ext`, `uploader`, `file`) |
| `GET /api/audit?kind=&result=&q=&limit=` | 감사 이벤트 조회 |
| `GET /api/audit/verify` | hash-chain 무결성 검증 |
| `GET /api/audit/export.csv` | CSV 내보내기 |
| `GET /api/keys` | MCP Key 목록 |
| `POST /api/keys` | Key 발급 (plaintext 1회 노출) |
| `DELETE /api/keys/{id}` | Key revoke |

## Job Step 필드

`POST /api/jobs`, `PATCH /api/jobs/{id}`의 `steps[]` 항목은 다음 필드를 사용합니다:

| 필드 | 설명 |
|---|---|
| `id` | Job 안에서 고유한 Step id |
| `cmd` | `shell=False`로 실행되는 argv 배열. 문자열 shell 명령은 거부 |
| `cwd` | 선택. Step 실행 디렉토리. 생략 시 `TASKFLOW_STEP_CWD` 사용 |
| `timeout` | Step timeout 초 |
| `deps` | 선행 Step id 배열 |
| `on_failure` | `STOP` / `CONTINUE` / `RETRY` / `ROLLBACK` |
| `env` | Step 전용 환경변수 |

`cd`, `pushd`, `popd`는 Step 명령으로 사용할 수 없습니다. 작업 디렉토리는 `cwd` 필드로 지정하세요.

## SSE 이벤트 포맷

```
event: run.started     data: {run_id, job_id, at}
event: step.started    data: {step_id, cmd, timeout}
event: step.log        data: {step_id, ts, lvl, text}
event: step.finished   data: {step_id, state, elapsed_sec}
event: run.finished    data: {run_id, status, failed_step, err_message, duration_sec}
event: ping            data: {}            # 30초마다 heartbeat
```

브라우저에서 `EventSource('/api/runs/{id}/stream')`로 바로 구독할 수 있습니다.

## 오류 코드

| HTTP | 의미 |
|---|---|
| `400 INVALID_ARTIFACT` | 해시/형식 불일치 |
| `401 UNAUTH` | Bearer 누락/유효하지 않은 key |
| `403 DENY` | scope 미매칭 |
| `404 NOT_FOUND` | job/run/artifact 없음 |
| `409 CONFLICT` | 동시성 차단 (`current_run_id` 포함) |
| `429 RATE_LIMIT` | rate-limit 초과 (`retry_after` 포함) |
| `202 SCANNING` | 아티팩트 스캔 중 |

Job 자체의 `FAILED`/`TIMEOUT`은 HTTP 에러가 아니라 응답 body의 `status` 필드로 전달됩니다.

## 관련 문서

- MCP를 통한 도구 호출 → [MCP API](./mcp-api.md)
- 포트/바인딩/CORS 설정 → [Operations](./operations.md)
- 보안 모델 → [Security](./security.md)
