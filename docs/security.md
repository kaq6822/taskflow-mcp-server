# Security Model

TaskFlow는 AI Agent가 임의의 커맨드를 실행할 수 있다는 점을 전제로 설계되었습니다. step의 `cmd`에는 argv 형식(리스트)이기만 하면 어떤 명령이든 등록할 수 있고, 사전 등록이나 백엔드 재시작 없이 즉시 실행됩니다. 즉 **Job을 만들거나 편집할 수 있다면 서버에서 임의 명령을 실행할 수 있습니다.**

> ⚠️ **Job 생성·편집 REST API에는 현재 인증이 없습니다.** `/api/jobs`에 도달할 수 있는 주체는 누구나 Job을 만들고 실행할 수 있으므로, 실질적인 사전 차단선은 **네트워크 접근 제어 하나뿐**입니다. MCP Key의 Scope는 MCP 경로(실행 `run:<job-id>`, 조회 `read:*`, 업로드 `write:uploads`)에만 적용되며 **Job 작성·편집에는 관여하지 않습니다** — MCP에는 Job을 만드는 도구 자체가 없습니다. 백엔드를 신뢰할 수 없는 네트워크에 노출하지 마세요.

실행 가능한 명령을 제한하지 않는 대신, TaskFlow는 실행 환경을 아래의 **강제되는 정책**으로 좁히고 실행된 모든 행위를 hash-chained audit 로그에 남겨 사후 추적 가능하게 합니다.

## 강제 정책

### 1. `shell=False`

Step 실행은 `asyncio.create_subprocess_exec(*argv)` 전용입니다. 코드베이스에 shell 문자열 실행 경로가 아예 존재하지 않습니다. argv가 리스트가 아니면 DAG 파싱 단계에서 거부됩니다. 이는 shell 메타문자(`;`, `|`, `&&`, 백틱 등)를 이용한 우회를 차단하지만, **어떤 프로그램이 실행되는지는 제한하지 않습니다.**

### 2. 제어된 cwd

Step은 기본적으로 `./storage/runtime`에서 실행됩니다. 이 기본값은 `TASKFLOW_STEP_CWD`로 override할 수 있습니다.

Job 작성자가 특정 Step의 실행 디렉토리를 제어해야 하면 Step의 `cwd` 필드를 사용합니다.

```json
{
  "id": "deploy",
  "cwd": "/opt/taskflow/apps/api",
  "cmd": ["./deploy.sh"],
  "timeout": 300
}
```

명시적 `cwd`는 비어 있으면 거부되고, 실행 시 존재하지 않거나 디렉토리가 아니면 해당 Step은 `FAILED`가 됩니다. `cd`, `pushd`, `popd`는 Step 명령으로 사용할 수 없습니다. 디렉토리 변경은 shell/process 상태 변경이라 다음 Step에 전달되지 않으므로 `cwd` 필드로 표현해야 합니다.

### 3. 시크릿 환경변수 마스킹

`SECRET_*` prefix의 환경변수는:

- 로그에서 값이 `***`로 마스킹됨
- 참조 시 `secret.read` audit 이벤트 기록

환경변수 이름 자체는 감사에 남지만 값은 DB/로그 어디에도 저장되지 않습니다.

### 4. Hash-chained audit

![Audit Log 화면](./assets/04-audit.png)

모든 감사 이벤트는 `prev_hash` + `sha256(canonical_body)` 체인으로 연결됩니다. 이벤트 하나를 수정하면 이후 체인이 전부 깨집니다.

```sh
curl http://localhost:8000/api/audit/verify
# { "ok": true, "count": 4821 }
```

변조 발생 시 `{"ok": false, "broken_at": N}` 반환. 자세한 대응은 [Troubleshooting](./troubleshooting.md) 참조.

### 5. MCP Key 보호

- DB에는 **hash만** 저장. plaintext는 발급 시 1회만 응답에 포함.
- Scope 매칭 + 토큰 버킷 rate-limit (`60/min` 등).
- 발급 / 회전 / revoke 모두 `auth.*` audit 이벤트 기록.
- 만료일 경과 시 자동 거부.

자세한 scope 규칙은 [MCP API §2](./mcp-api.md#2-scope-규칙) 참조.

## 남은 정책을 우회할 수 없는 이유

- Job 생성 시점(UI/REST) — DAG 파서가 argv 형식과 `cwd` 형식 검증 + shell 문자열/상태 변경 명령 거부
- Run 시작 시점 — policies.py가 상태 변경 명령(`cd`/`pushd`/`popd`)을 재검증
- subprocess 시점 — `create_subprocess_exec`는 shell 해석을 수행하지 않음 (execve 직행)

세 지점 중 어디서든 실패하면 `policy.violation` audit + run FAILED로 이어집니다. 다만 이 검사들은 **무엇이 실행되는지**를 보지 않습니다 — argv 형식으로 표현되었는지, 그리고 worker의 작업 디렉터리를 바꾸려 들지 않는지만 확인합니다.

## 범위 밖 (현재 미구현)

보안 모델상 다음은 스코프 밖입니다:

- 네트워크 egress 제어 (방화벽/seccomp) — OS 계층으로 위임
- 컨테이너/namespace 격리 — 현재 프로세스 격리는 cwd 제어 수준
- SIEM forward — 로컬 audit 테이블만 제공 (`GET /api/audit/export.csv`)
- ClamAV 실제 연동 — 현재 stub (업로드 즉시 READY)
- **REST API 인증** — `/api/*` 라우트에는 인증 의존성이 없습니다. `bootstrap.py`가 admin 세션 토큰을 발급하지만 검증하는 경로가 없습니다.
- **전용 저권한 계정 / no-root 실행** — worker는 `subprocess.Popen`에 `user=`나 uid drop을 넘기지 않습니다. Step은 백엔드를 실행한 계정 권한 그대로 동작합니다.

## 관련 문서

- 정책 상세 구현 → `backend/app/engine/policies.py`
- 감사 이벤트 종류 → [02-business-rules.md](./02-business-rules.md)
- MCP Key scope 매칭 → [MCP API](./mcp-api.md)
