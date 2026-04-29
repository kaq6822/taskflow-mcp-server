# Security Model

TaskFlow는 AI Agent가 임의의 커맨드를 실행할 수 있다는 점을 전제로 설계되어, **강제되는 정책**으로 사고를 사전 차단합니다.

## 강제 정책

### 1. `shell=False`

Step 실행은 `asyncio.create_subprocess_exec(*argv)` 전용입니다. 코드베이스에 shell 문자열 실행 경로가 아예 존재하지 않습니다. argv가 리스트가 아니면 DAG 파싱 단계에서 거부됩니다.

### 2. argv allowlist

로컬 allowlist(`backend/app/dev/allowlist.yaml` — **환경별 사본**, `.gitignore` 제외)에 명시된 argv 프리픽스만 실행 가능합니다. 미매칭 시 `policy.violation` audit + DENY. 공유 템플릿은 `backend/app/dev/allowlist.example.yaml`이며 `make setup`이 첫 설치 시 사본을 생성합니다. 프로덕션에서는 `TASKFLOW_ALLOWLIST_PATH`로 저장소 밖의 경로를 지정하는 것을 권장합니다.

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

추가가 필요한 경우:

```yaml
allow:
  - ["npm", "ci"]
  - ["npm", "run", "build"]
  - ["aws", "s3", "sync"]
```

프리픽스 매칭이므로 `["npm", "ci"]`는 `npm ci --silent`를 허용하지만 `npm install`은 거부됩니다.

### 3. 제어된 cwd

Step은 기본적으로 `./storage/runtime`에서 실행됩니다. 이 기본값은 `TASKFLOW_STEP_CWD`로 override할 수 있습니다.

Job 작성자가 특정 Step의 실행 디렉토리를 제어해야 하면 Step의 `cwd` 필드를 사용합니다.

```json
{
  "id": "deploy",
  "cwd": "/cms/cms_api",
  "cmd": ["./deploy.sh"],
  "timeout": 300
}
```

명시적 `cwd`는 비어 있으면 거부되고, 실행 시 존재하지 않거나 디렉토리가 아니면 해당 Step은 `FAILED`가 됩니다. `cd`, `pushd`, `popd`는 Step 명령으로 사용할 수 없습니다. 디렉토리 변경은 shell/process 상태 변경이라 다음 Step에 전달되지 않으므로 `cwd` 필드로 표현해야 합니다.

### 4. 시크릿 환경변수 마스킹

`SECRET_*` prefix의 환경변수는:

- 로그에서 값이 `***`로 마스킹됨
- 참조 시 `secret.read` audit 이벤트 기록

환경변수 이름 자체는 감사에 남지만 값은 DB/로그 어디에도 저장되지 않습니다.

### 5. Hash-chained audit

![Audit Log 화면](./assets/04-audit.png)

모든 감사 이벤트는 `prev_hash` + `sha256(canonical_body)` 체인으로 연결됩니다. 이벤트 하나를 수정하면 이후 체인이 전부 깨집니다.

```sh
curl http://localhost:8000/api/audit/verify
# { "ok": true, "count": 4821 }
```

변조 발생 시 `{"ok": false, "broken_at": N}` 반환. 자세한 대응은 [Troubleshooting](./troubleshooting.md) 참조.

### 6. MCP Key 보호

- DB에는 **hash만** 저장. plaintext는 발급 시 1회만 응답에 포함.
- Scope 매칭 + 토큰 버킷 rate-limit (`60/min` 등).
- 발급 / 회전 / revoke 모두 `auth.*` audit 이벤트 기록.
- 만료일 경과 시 자동 거부.

자세한 scope 규칙은 [MCP API §2](./mcp-api.md#2-scope-규칙) 참조.

## 정책 우회가 불가능한 이유

- Job 생성 시점(UI/REST) — DAG 파서가 argv 형식과 `cwd` 형식 검증 + shell 문자열/상태 변경 명령 거부
- Run 시작 시점 — policies.py가 allowlist와 상태 변경 명령 재검증
- subprocess 시점 — `create_subprocess_exec`는 shell 해석을 수행하지 않음 (execve 직행)

세 지점 모두에서 실패 시 `policy.violation` audit + run FAILED.

## 범위 밖 (현재 미구현)

보안 모델상 다음은 스코프 밖입니다:

- 네트워크 egress 제어 (방화벽/seccomp) — OS 계층으로 위임
- 컨테이너/namespace 격리 — 현재 프로세스 격리는 cwd 제어 수준
- SIEM forward — 로컬 audit 테이블만 제공 (`GET /api/audit/export.csv`)
- ClamAV 실제 연동 — 현재 stub (업로드 즉시 READY)

## 관련 문서

- 정책 상세 구현 → `backend/app/engine/policies.py`, `backend/app/dev/allowlist.example.yaml`(템플릿), `backend/app/dev/allowlist.yaml`(환경별 로컬 사본)
- 감사 이벤트 종류 → [02-business-rules.md](./02-business-rules.md)
- MCP Key scope 매칭 → [MCP API](./mcp-api.md)
