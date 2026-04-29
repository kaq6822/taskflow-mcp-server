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

### `curl http://127.0.0.1:5173`이 실패

Vite 기본 dev 서버는 `localhost` (IPv6 우선)만 바인드합니다.

- `curl http://localhost:5173/`을 쓰거나
- `vite.config.ts`에 `server.host = '0.0.0.0'`을 추가하거나
- `make dev-lan`을 사용하세요 ([Operations](./operations.md) 참조).

## MCP

### MCP 호출이 `400 Bad Request`로 실패

모든 MCP 호출(최초 `initialize` 제외)은 `Mcp-Session-Id` 헤더를 요구합니다. `initialize` 응답 헤더에서 값을 추출해 이후 호출에 포함시켜야 합니다.

또한 `Accept: application/json, text/event-stream` 헤더도 필요합니다. 자세한 curl 예시는 [MCP API §3](./mcp-api.md#3-json-rpc로-직접-호출).

### MCP 호출이 `401 UNAUTH`

- `Authorization: Bearer <token>` 헤더가 빠졌거나
- plaintext 토큰이 DB hash와 일치하지 않거나
- Key가 만료/revoke되었습니다.

Key 목록·상태는 UI `MCP Key` 화면 또는 `GET /api/keys`로 확인.

### MCP 호출이 `403 DENY`

Key의 scope가 도구 요구 scope와 불일치합니다. 예:

- `read:jobs`만 가진 Key로 `run_job` 호출 → DENY
- `run:foo`만 가진 Key로 `run_job(job_id="bar")` 호출 → DENY

Scope 매칭 규칙은 [MCP API §2](./mcp-api.md#2-scope-규칙).

## 실행

### allowlist에 없는 커맨드로 Job 실행이 즉시 `policy.violation`

의도된 동작입니다. 환경별 로컬 사본 `backend/app/dev/allowlist.yaml`(템플릿 아님)에 argv 프리픽스를 추가하고 backend를 재시작하세요. 사본이 없다면 `make bootstrap-allowlist`로 템플릿(`backend/app/dev/allowlist.example.yaml`)에서 복사합니다. 프로덕션에서는 `TASKFLOW_ALLOWLIST_PATH`로 저장소 밖 경로를 지정하는 것이 안전합니다.

```yaml
allow:
  - ["npm", "ci"]
  - ["npm", "run", "build"]
  - ["aws", "s3", "sync"]
```

정책 배경은 [Security](./security.md).

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
- allowlist 미매칭으로 거부되었는데 UI가 아직 상태 폴링 중

`backend/storage/logs/<run_id>/<step_id>.log` 파일에 stderr가 기록됩니다.

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
# { "ok": false, "broken_at": 128 }
```

128번째 이벤트부터 체인이 깨진 것입니다. 정상 운영 상태라면 절대 발생하지 않습니다. 대응:

1. `GET /api/audit?limit=200`으로 128번 근처 이벤트 덤프
2. 변조 의심 시 DB 백업 즉시 확보 + 인시던트 기록
3. 정상화가 필요하면 `make reset` (주의: 모든 Job/Run/Key/Audit 손실)

## Frontend

### Dashboard가 비어있음

빈 DB 상태이므로 정상입니다. `+ 새 Job`으로 시작하세요. [Getting Started](./getting-started.md).

### SSE 스트림이 끊김

- 리버스 프록시(Nginx/Cloudflare 등)에서 `proxy_buffering off`, `proxy_read_timeout`을 길게 설정
- 30초 이상 idle 시 `event: ping`이 자동 주입되어 연결 유지
