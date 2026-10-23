# Troubleshooting

실제 발생했던 증상 모음입니다. 새로운 케이스를 발견하면 PR로 추가해 주세요.

## 설치 · 환경

### Python 3.14에서 `greenlet` 누락 에러

```
ValueError: the greenlet library is required to use this function.
```

해결:

```sh
backend/.venv/bin/pip install "greenlet>=3.0"
```

`backend/pyproject.toml`에 이미 명시되어 있으므로 `make setup` 재실행으로도 해결됩니다.

### 업그레이드 후 `no such column: jobs.params` / `runs.params` / `runs.outputs`

새 버전의 DB 마이그레이션(`0003_run_params`, `0004_run_outputs`, `0005_single_running_run`, `0006_drop_run_runner` 등)이 적용되지 않았습니다. 서버 기동 시의 테이블 자동 생성은 기존 테이블에 컬럼을 추가하지 않습니다.

```sh
make migrate
```

후 서버를 재기동하세요. [Operations — 업그레이드](./operations.md#업그레이드) 참고.

### 업그레이드했는데 UI가 그대로임 (`make start` / `make start-bg`)

프로덕션 모드는 `frontend/dist`를 서빙하며, `dist`가 이미 있으면 다시 빌드하지 않습니다. `make build` 후 재기동하세요.

### `curl http://127.0.0.1:5173`이 실패

Vite 기본 dev 서버는 `localhost` (IPv6 우선)만 바인드합니다.

- `curl http://localhost:5173/`을 쓰거나
- `vite.config.ts`에 `server.host = '0.0.0.0'`을 추가하거나
- `make dev-lan`을 사용하세요 ([Operations](./operations.md) 참조).

## MCP

### MCP 호출이 `406 Not Acceptable` / `415` / `400`으로 실패

- `406` — `Accept: application/json, text/event-stream` 헤더가 빠졌습니다.
- `415` — `Content-Type: application/json`이 아닙니다.
- `400` — body가 올바른 JSON-RPC 메시지가 아닙니다.

서버는 stateless 모드라 `Mcp-Session-Id`는 필요 없습니다. 자세한 curl 예시는 [MCP API §3](./mcp-api.md#3-json-rpc로-직접-호출).

### MCP 호출이 `401 UNAUTH`

- `Authorization: Bearer <token>` 헤더가 빠졌거나
- plaintext 토큰이 DB hash와 일치하지 않거나
- Key가 만료/revoke되었습니다.

Key 목록·상태는 UI `MCP Key` 화면 또는 `GET /api/keys`로 확인.

### MCP tool 호출 결과가 `DENY: scope '…' not permitted`

HTTP는 200이지만 tool 결과가 오류(`isError: true`)입니다. Key의 scope가 도구 요구 scope와 불일치합니다. 예:

- `read:jobs`만 가진 Key로 `run_job` 호출 → DENY
- `run:foo`만 가진 Key로 `run_job(job_id="bar")` 호출 → DENY

Scope 매칭 규칙은 [MCP API §2](./mcp-api.md#2-scope-규칙).

## 실행

### Run 트리거가 `UNKNOWN_PARAM` / `INVALID_PARAM`으로 거부됨

- `UNKNOWN_PARAM` — Job이 선언하지 않은 이름을 보냈습니다. 파라미터를 선언하지 않은 Job에 `params`를 보내도 이 오류입니다. Job의 `params`(`GET /api/jobs/{id}`, MCP `get_job`)를 확인하세요.
- `INVALID_PARAM` — 기본값 없는 파라미터를 빠뜨렸거나, 값이 `pattern` 전체와 일치하지 않거나, 문자열이 아니거나, 빈 값·앞뒤 공백·제어문자·1024자 초과입니다. 메시지에 어느 파라미터가 왜 거부됐는지 나옵니다.

자세한 규칙은 [Run 파라미터](./run-params.md).

### `::output`을 찍었는데 Run의 `outputs`가 비어 있음

step 로그에서 경고를 확인하세요.

- `output ignored: …` — 형식 오류(`key=value` 아님, key 규칙 위반, 빈 값·앞뒤 공백·제어문자·1024자 초과)
- `outputs discarded: step ended FAILED` — 출력값은 SUCCESS로 끝난 step의 것만 기록됩니다
- 아무 경고도 없다면 stderr로 찍었거나(`echo … >&2`) 줄 맨 앞이 `::output `으로 시작하지 않는 경우입니다

자세한 규칙은 [Run 출력값](./run-outputs.md).

### `cd /path` Step이 `policy.violation`으로 거부됨

의도된 동작입니다. `cd`는 shell/process 상태 변경 명령이라 별도 subprocess로 실행해도 다음 Step의 작업 디렉토리를 바꾸지 못합니다. Step의 `cwd` 필드를 사용하세요.

```json
{
  "id": "deploy",
  "cwd": "/opt/taskflow/apps/api",
  "cmd": ["./deploy.sh"]
}
```

`pushd`, `popd`도 같은 이유로 거부됩니다.

### Run이 `RUNNING`에서 진행되지 않음

최신 버전에서는 실행 파일 없음, 권한 없음, 잘못된 `cwd` 같은 subprocess 시작 실패가 Step `FAILED`로 정리됩니다. 이전 버전에서 남은 Run이라면 Dashboard/Job 상세/Logs 화면의 정지 버튼 또는 `POST /api/runs/{id}/cancel`로 취소하세요.

Backend 로그에서 `Task exception was never retrieved`를 확인하세요. 대부분 다음 중 하나입니다:

- 대상 커맨드가 존재하지 않음 (`ENOENT`)
- 명시한 `cwd`가 존재하지 않거나 디렉토리가 아님
- `cd`/`pushd`/`popd`를 step 명령으로 써서 `policy.violation`으로 거부되었는데 UI가 아직 상태 폴링 중

`backend/storage/logs/<run_id>/<step_id>.log` 파일에 stderr가 기록됩니다.

### 실행 중인 Run이 없는데 트리거가 `409 CONFLICT`

Job당 `RUNNING` Run은 DB에서 1개로 제한됩니다. 서버가 Run 도중 종료되면 그 Run은 `RUNNING`으로 남지만, 서버가 다시 기동할 때 남아 있는 `RUNNING` Run을 모두 `FAILED`(`서버 재시작으로 중단`)로 정리합니다. 재기동 전까지는 그 Job이 계속 막힙니다. `0005_single_running_run` 이전에 시작된 Run도 같이 정리됩니다.

기다릴 수 없다면 409 응답의 `current_run_id`(MCP는 `… already running as #<run_id>`)를 `POST /api/runs/{id}/cancel`로 취소하면 다시 실행할 수 있습니다.

### Step이 exit 0인데 `FAILED`가 됨

Step에 출력 assertion이 설정되어 있는지 확인하세요.

- `failure_contains`에 지정한 문자열이 stdout/stderr에 포함되면 실패합니다.
- `success_contains`에 지정한 문자열이 하나라도 누락되면 실패합니다.

Run 로그의 `output assertion failed: ...` 메시지와 `backend/storage/logs/<run_id>/<step_id>.log`를 함께 확인하세요.

### Run이 `TIMEOUT`으로 끝남

Step의 `timeout` 필드가 초 단위로 너무 짧게 잡혀있을 수 있습니다. Builder에서 timeout을 조정한 뒤 재실행.

## 감사 로그

### Audit chain verify가 FAIL

DB row가 수동으로 변조되었거나 timezone 처리 버그일 수 있습니다.

```sh
curl http://localhost:8000/api/audit/verify
# FAIL: broken at id=128
```

id 128 이벤트부터 체인이 깨진 것입니다. 정상 운영 상태라면 절대 발생하지 않습니다. 대응:

1. `GET /api/audit?limit=200`으로 128번 근처 이벤트 덤프
2. 변조 의심 시 DB 백업 즉시 확보 + 인시던트 기록
3. 정상화가 필요하면 `make reset` (주의: 모든 Job/Run/Key/Audit 손실)

## Frontend

### Dashboard가 비어있음

빈 DB 상태이므로 정상입니다. `+ 새 Job`으로 시작하세요. [Getting Started](./getting-started.md).

### SSE 스트림이 끊김

- 리버스 프록시(Nginx/Cloudflare 등)에서 `proxy_buffering off`, `proxy_read_timeout`을 길게 설정
- 30초 이상 idle 시 `event: ping`이 자동 주입되어 연결 유지
