# 아티팩트를 사용하는 Job 작성 가이드

[Artifacts 가이드](./artifacts.md)가 "아티팩트가 어떻게 동작하는가"를 다룬다면, 이 문서는 **"그래서 Job을 어떻게 짜는가"** 에 답한다. 복사해서 고쳐 쓸 수 있는 골격과 패턴을 모았다.

---

## 0. 준비: allowlist에 실행기 등록

아티팩트를 다루는 Job은 거의 항상 스크립트를 실행한다. 그런데 step의 `cmd`는 `shell=False`로 실행되고, 실행할 명령은 **argv allowlist에 등록돼 있어야 한다.** `/bin/bash`는 기본 allowlist에 없다.

`backend/app/dev/allowlist.yaml`을 편집한다(없으면 `make bootstrap-allowlist`).

```yaml
allow:
  - ["echo"]
  - ["printf"]
  - ["cat"]
  - ["/usr/bin/shasum"]
  # 이 문서의 예제들은 storage/runtime의 스크립트를 상대 경로로 실행한다
  - ["/bin/bash", "deploy.sh"]
  - ["/bin/bash", "verify.sh"]
  # 절대 경로로 실행하면 위치까지 고정할 수 있다
  - ["/bin/bash", "/opt/taskflow/scripts/migrate.sh"]
```

> **항목은 step의 `cmd`와 같은 형태로 적어야 한다.** 원소끼리 문자열 비교하므로, `cmd`가 `["/bin/bash", "deploy.sh"]`인데 allowlist에는 절대 경로로 적어두면 매칭되지 않는다. 스크립트마다 항목이 하나씩 필요하다.

각 항목은 **argv의 앞부분(prefix)** 과 매칭된다. `["echo"]`는 `echo`로 시작하는 모든 호출을 허용하고, `["/bin/bash", "/opt/…/deploy.sh"]`는 그 스크립트를 실행하는 경우만 허용한다.

`*`를 쓸 수 있지만 **원소 하나를 통째로 대체하는 와일드카드이고, 경로 glob이 아니다.**

| 항목 | `/bin/bash /opt/taskflow/scripts/deploy.sh` 매칭 |
|---|---|
| `["/bin/bash", "/opt/taskflow/scripts/deploy.sh"]` | ✅ 정확히 일치 |
| `["/bin/bash", "*"]` | ✅ 두 번째 원소가 무엇이든 허용 |
| `["/bin/bash"]` | ✅ prefix만 검사하므로 무엇이든 허용 |
| `["/bin/bash", "/opt/taskflow/scripts/*"]` | ❌ **매칭되지 않음** — `*`가 포함된 문자열과 그대로 비교한다 |

즉 "특정 디렉터리의 스크립트만" 같은 제한은 표현할 수 없다. 허용할 스크립트를 하나씩 나열해야 한다.

또한 **prefix 검사이므로 등록한 원소 뒤에 인자를 더 붙이는 것은 허용된다.** `["/bin/bash", "deploy.sh"]`는 `/bin/bash deploy.sh --force`도 통과시킨다. 스크립트가 받는 인자까지 제한하려면 그 인자를 항목에 포함해야 한다.

> **`["/bin/bash"]`나 `["/bin/bash", "*"]`는 임의의 스크립트를 실행할 수 있게 만든다.** 두 번째 원소에 스크립트 경로를 정확히 적어 좁히는 편이 안전하다.

편집 후 **백엔드를 재시작**해야 적용된다. 등록되지 않은 명령으로 Job을 저장하면 `400`으로 거부된다.

```json
{"detail": "argv not in allowlist: /bin/bash"}
```

---

## 1. 가장 짧은 골격

아티팩트 하나를 받아 배포하는 최소 구성이다.

**① 업로드**

```bash
curl -X POST http://localhost:8000/api/artifacts \
  -F name=myapp -F version=v1.2.0 -F ext=jar -F uploader=ci -F file=@build/myapp.jar
```

**② 스크립트 배치** — step의 기본 작업 디렉터리인 `storage/runtime/`에 둔다(또는 `cwd`를 지정해 다른 위치를 쓴다).

```bash
# storage/runtime/deploy.sh
#!/usr/bin/env bash
set -euo pipefail
cp "$ARTIFACT_JAR_PATH" ./app.jar     # 원본은 0444라 복사해서 쓴다
java -jar ./app.jar
echo "DEPLOY_OK"
```

**③ Job 등록**

```json
{
  "id": "deploy-app",
  "name": "Deploy App",
  "owner": "ops",
  "consumes_artifacts": [{"alias": "jar", "name": "myapp"}],
  "steps": [
    {
      "id": "deploy",
      "cmd": ["/bin/bash", "deploy.sh"],
      "timeout": 300,
      "deps": [],
      "success_contains": ["DEPLOY_OK"]
    }
  ]
}
```

**④ 실행** — `artifact_refs`를 생략하면 최신 업로드가 쓰인다.

```bash
curl -X POST http://localhost:8000/api/jobs/deploy-app/runs \
  -H 'Content-Type: application/json' -d '{}'
```

---

## 2. 작성 체크리스트

| 단계 | 확인할 것 | 빠뜨리면 |
|---|---|---|
| ① allowlist | 실행할 명령이 `allowlist.yaml`에 있고 백엔드를 재시작했는가 | Job 저장 시 `400 argv not in allowlist` |
| ② 스크립트 위치 | `storage/runtime/`에 있는가, 또는 step에 `cwd`를 지정했는가 | `exit 127 executable not found` 또는 `126 cwd not found` |
| ③ alias 선언 | `consumes_artifacts`에 alias가 있는가 | `ARTIFACT_*`가 주입되지 않음 (조용히 빈 변수) |
| ④ cmd | 환경변수를 스크립트 **안에서** 읽는가 | `$ARTIFACT_...`가 문자열 그대로 전달됨 |
| ⑤ 판정 | 성공 조건이 exit code만으로 충분한가 | 실패를 성공으로 오판 |

---

## 3. step 구성 패턴

### 3.1 순서 제어 — `deps`

`deps`는 실행 **순서**를 정한다. 위상 정렬 결과대로 **순차 실행**되며, 의존 관계가 없는 step이 병렬로 돌지는 않는다.

```json
"steps": [
  {"id": "verify",  "cmd": ["/bin/bash", "verify.sh"],  "timeout": 60,  "deps": []},
  {"id": "deploy",  "cmd": ["/bin/bash", "deploy.sh"],  "timeout": 300, "deps": ["verify"]},
  {"id": "health",  "cmd": ["/bin/bash", "health.sh"],  "timeout": 60,  "deps": ["deploy"]}
]
```

순환 의존은 저장 시점에 `cycle detected: a → b → a`로 거부되고, 존재하지 않는 step을 참조하면 `depends on unknown step '…'`으로 거부된다.

앞선 step이 실패해 run이 실패로 전환되면 **이후 step은 모두 `SKIPPED`** 가 된다.

### 3.2 아티팩트 무결성 검증

`ARTIFACT_<ALIAS>_SHA256`은 업로드 시 계산된 해시다. 배포 전에 파일과 대조할 수 있다.

```bash
# storage/runtime/verify.sh
#!/usr/bin/env bash
set -euo pipefail
actual=$(shasum -a 256 "$ARTIFACT_JAR_PATH" | cut -d' ' -f1)
if [ "$actual" != "$ARTIFACT_JAR_SHA256" ]; then
  echo "SHA_MISMATCH expected=$ARTIFACT_JAR_SHA256 actual=$actual"
  exit 1
fi
echo "SHA_OK $ARTIFACT_JAR_REF"
```

### 3.3 출력 기반 성공/실패 판정

exit code만으로 부족할 때 `success_contains`(반드시 나와야 하는 문자열)와 `failure_contains`(나오면 안 되는 문자열)를 쓴다. stdout과 stderr 모두를 대상으로 하는 **부분 문자열** 검사다(정규식이 아니다).

```json
{
  "id": "deploy",
  "cmd": ["/bin/bash", "deploy.sh"],
  "timeout": 300,
  "deps": [],
  "success_contains": ["DEPLOY_OK"],
  "failure_contains": ["OutOfMemoryError", "Connection refused"]
}
```

판정 우선순위는 다음과 같다.

| 상황 | 결과 |
|---|---|
| `failure_contains`에 걸림 | **FAILED** — exit code가 0이어도 실패 |
| exit 0 + `success_contains` 전부 발견 | SUCCESS |
| exit 0 + `success_contains` 중 누락 | **FAILED** (`missing required text …`) |
| exit ≠ 0 | FAILED (`non-zero exit N`) |

`failure_contains`가 가장 강하다는 점이 핵심이다. 성공 종료 코드를 반환하면서 로그에만 오류를 남기는 배포 도구를 잡아낼 수 있다.

### 3.4 실패 처리 — `on_failure`

step에 지정하면 Job 기본값을 덮어쓴다.

| 값 | 동작 |
|---|---|
| `STOP` | 이후 step을 `SKIPPED`로 두고 run을 FAILED로 종료 (기본값) |
| `CONTINUE` | 실패를 기록하지 않고 다음 step으로 진행 |
| `RETRY` | **1회만** 재시도. 재시도가 성공하면 첫 실패 기록을 지운다 |
| `ROLLBACK` | ⚠️ 현재 구현은 `STOP`과 **동일하게** 동작한다 |

> **`ROLLBACK`은 아무것도 되돌리지 않는다.** 되돌리는 동작이 필요하면 보상 step을 직접 작성하고, 실패 시 그 step까지 도달하도록 앞 step을 `CONTINUE`로 두는 식으로 구성해야 한다. 이름만 보고 자동 롤백을 기대하면 안 된다.

일시적 네트워크 오류에 재시도를 붙이고, 배포 본체는 멈추게 하는 구성 예시다.

```json
"steps": [
  {"id": "fetch",  "cmd": ["/bin/bash", "fetch.sh"],  "timeout": 60,  "deps": [], "on_failure": "RETRY"},
  {"id": "deploy", "cmd": ["/bin/bash", "deploy.sh"], "timeout": 300, "deps": ["fetch"], "on_failure": "STOP"}
]
```

### 3.5 아티팩트 여러 개 조합

alias는 step이 보는 이름이므로, 아티팩트 이름이 아니라 **역할**로 짓는 편이 읽기 쉽다.

```json
{
  "id": "release",
  "name": "Release",
  "owner": "ops",
  "consumes_artifacts": [
    {"alias": "app",       "name": "myapp"},
    {"alias": "conf",      "name": "myapp-config"},
    {"alias": "migration", "name": "myapp-db-migration"}
  ],
  "steps": [
    {"id": "migrate", "cmd": ["/bin/bash", "migrate.sh"], "timeout": 600, "deps": []},
    {"id": "deploy",  "cmd": ["/bin/bash", "deploy.sh"],  "timeout": 300, "deps": ["migrate"]}
  ]
}
```

세 alias 모두 **모든 step**에 주입된다. `migrate.sh`는 `$ARTIFACT_MIGRATION_PATH`를, `deploy.sh`는 `$ARTIFACT_APP_PATH`와 `$ARTIFACT_CONF_PATH`를 쓰면 된다. step별로 일부만 주입하는 기능은 없다.

alias 규칙은 `^[A-Za-z][A-Za-z0-9_]*$`이고 대소문자를 무시해 중복을 검사한다. `db-migration`처럼 `-`를 넣으면 저장이 거부된다.

### 3.6 작업 디렉터리 — `cwd`

지정하지 않으면 `storage/runtime`이 쓰이고, 없으면 자동 생성된다. **명시적으로 지정하면 그 디렉터리가 미리 존재해야 한다.**

```json
{"id": "deploy", "cmd": ["/bin/bash", "/opt/taskflow/scripts/deploy.sh"],
 "cwd": "/opt/taskflow/work", "timeout": 300, "deps": []}
```

없는 경로를 주면 `exit 126 cwd not found: …`로 실패한다. `cd`·`pushd`·`popd`는 step 명령으로 쓸 수 없다(저장 시 거부) — 디렉터리 이동은 `cwd`로 표현한다.

---

## 4. 안티패턴

| 하지 말 것 | 왜 | 대신 |
|---|---|---|
| `"cmd": ["cp", "$ARTIFACT_JAR_PATH", "./a.jar"]` | `shell=False`라 확장되지 않고 문자열이 그대로 전달됨 | 스크립트로 감싸고 그 안에서 참조 |
| `"cmd": ["cd", "/opt/app"]` | 하위 프로세스는 워커의 cwd를 바꿀 수 없음 (저장 시 거부) | step의 `cwd` 사용 |
| 아티팩트 경로를 하드코딩 | 버전이 바뀌면 깨지고 pinning 기록과 어긋남 | `$ARTIFACT_<ALIAS>_PATH` 사용 |
| 원본 파일을 제자리에서 수정·해제 | 0444로 잠겨 있음 | 작업 디렉터리로 복사한 뒤 처리 |
| step `env`로 `ARTIFACT_*` 지정 | 무시되고 경고만 남음 | 다른 이름의 변수를 쓴다 |
| alias에 `-`·`.` 사용 | 환경변수 키로 쓸 수 없음 | `_` 사용 (`db_migration`) |
| 실행 때마다 `@latest`에 의존 | 어떤 빌드가 나갔는지 사후 특정이 어려움 | 배포는 `artifact_refs`로 버전 명시 |
| `on_failure: "ROLLBACK"`에 되돌리기를 기대 | `STOP`과 동일하게 동작 | 보상 step을 직접 작성 |

---

## 5. CI → Agent 전체 흐름

CI가 빌드 산출물을 올리고, Agent가 버전을 명시해 실행하는 구성이다.

**① CI: 업로드** (`write:uploads` scope)

```bash
curl -fsS -X POST "$TASKFLOW/api/artifacts" \
  -F name=myapp -F "version=$GIT_SHA" -F ext=jar \
  -F uploader=ci -F file=@build/myapp.jar
```

**② Agent: 버전을 고정해 실행** (`run:<job_id>` scope)

```
run_job(
  job_id="deploy-app",
  mode="sync",
  artifact_refs={"jar": "uploads://myapp@<GIT_SHA>"},
  idempotency_key="deploy-<GIT_SHA>"
)
```

`idempotency_key`를 주면 같은 키로 다시 호출해도 새 run이 생기지 않고 기존 run이 반환되므로, 재시도가 중복 배포로 이어지지 않는다.

> 키는 **테이블 전체에서 유일**하다. 여러 Job을 같은 커밋으로 배포한다면 Job마다 키를 다르게 잡아야 한다(`deploy-app-<SHA>`, `deploy-worker-<SHA>`). 다른 Job에서 같은 키를 재사용하면 `CONFLICT`로 거부된다.

**③ 결과 확인** — 응답의 `artifact_refs`에는 실제로 배포된 구체 버전과 sha256이 남는다.

```json
{
  "status": "SUCCESS",
  "artifact_refs": {"jar": {"ref": "uploads://myapp@a1b2c3d", "sha256": "…"}},
  "steps": [{"id": "deploy", "state": "SUCCESS", "elapsed_sec": 12.4}]
}
```

---

## 6. 배포 전 점검

- [ ] 실행할 명령이 allowlist에 있고, 필요 이상으로 넓지 않은가
- [ ] 스크립트가 `set -euo pipefail`로 시작하는가 (중간 실패를 삼키지 않도록)
- [ ] 아티팩트를 복사한 뒤 다루는가
- [ ] 성공 판정이 exit code만으로 충분한가, `success_contains`가 필요한가
- [ ] `timeout`이 실제 소요 시간보다 넉넉한가 (초과 시 `TIMEOUT`)
- [ ] 배포 Job은 `artifact_refs`로 버전을 명시하는가
- [ ] `ROLLBACK`에 자동 되돌리기를 기대하고 있지 않은가

---

## 관련 문서

- [Artifacts](./artifacts.md) — 업로드·환경변수·버전 고정의 동작 원리
- [Getting Started](./getting-started.md) — 설치와 첫 Job
- [Security](./security.md) — allowlist 설계, 시크릿 마스킹, 감사 로그
- [Troubleshooting](./troubleshooting.md) — 증상별 해결
