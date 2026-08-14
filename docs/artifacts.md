# Artifacts 가이드

빌드 산출물(jar, tar.gz, 이미지 등)을 TaskFlow에 올리고, Job의 step이 그 파일을 **경로로** 받아 쓰는 방법을 설명한다.

핵심 개념은 하나다. **step은 아티팩트를 직접 찾지 않는다.** Job이 "이 아티팩트를 소비한다"고 alias로 선언하면, TaskFlow가 실행 시점에 버전을 골라 고정(pin)하고 그 경로를 환경변수로 넘겨준다.

```
① 업로드                ② Job에서 선언              ③ step에서 사용
┌──────────────┐      ┌───────────────────┐      ┌────────────────────────┐
│ myapp@v1.2.0 │─────▶│ consumes_artifacts│─────▶│ $ARTIFACT_JAR_PATH     │
│ (파일 + sha) │      │ [{alias:"jar",    │      │ /…/storage/artifacts/  │
└──────────────┘      │   name:"myapp"}]  │      │   ab/myapp-v1.2.0.jar  │
                      └───────────────────┘      └────────────────────────┘
                                  │
                        ④ Run 시작 시 버전 고정
                        artifact_refs: {"jar": {ref:"uploads://myapp@v1.2.0", sha256:"…"}}
```

alias(`jar`)와 아티팩트 이름(`myapp`)을 분리한 이유는 두 가지다. 아티팩트 이름을 바꿔도 배포 스크립트가 참조하는 환경변수는 그대로 유지되고, 이름에 쓸 수 있는 `.`·`-`가 환경변수 키에서 충돌하는 문제(`my-app`과 `my.app`이 둘 다 `MY_APP`이 됨)를 피할 수 있다.

---

## 1. 업로드

세 가지 경로가 있고 결과는 동일하다.

### 웹 UI

**Artifacts** 화면 → 우측 상단 **Upload** → `name` · `version` · `ext` 입력 후 파일 선택 → 업로드.

### REST

`multipart/form-data`로 보낸다.

```bash
curl -X POST http://localhost:8000/api/artifacts \
  -F name=myapp \
  -F version=v1.2.0 \
  -F ext=jar \
  -F uploader=ci \
  -F file=@build/myapp.jar
```

| 필드 | 필수 | 기본값 | 설명 |
|---|---|---|---|
| `name` | ✅ | — | 아티팩트 이름. Job이 이 이름으로 선언한다 |
| `version` | ✅ | — | 버전 문자열. 의미는 자유(`v1.2.0`, `build-417`, 커밋 SHA 등) |
| `ext` | | `tar.gz` | 확장자. 저장 파일명에만 쓰인다 |
| `uploader` | | `admin` | 감사 로그에 기록되는 주체 |
| `file` | ✅ | — | 파일 본문 |

### MCP (Agent)

```
upload_artifact(name="myapp", version="v1.2.0", content_base64="<base64>", ext="jar")
```

필요 scope는 `write:uploads`. 응답은 `{artifact_id, name, version, sha256, status, size_bytes}`.

### 업로드가 하는 일

1. 스트리밍하며 SHA-256을 계산한다
2. `storage/artifacts/<sha256 앞 2자리>/<name>-<version>.<ext>`로 저장하고 **0444(읽기 전용)** 로 잠근다
3. 같은 `name`의 기존 `latest` 플래그를 내리고, 새 행을 `latest`로 세운다
4. 감사 이벤트 `artifact.upload`을 남긴다 (`target=<name>@<version>`)

### 제약

| 규칙 | 위반 시 |
|---|---|
| `name` · `version` · `ext`는 `[A-Za-z0-9._-]`만 허용하고 `..`, `/`, `\`를 금지 | `400` (경로 탈출 방지) |
| `(name, version)` 조합은 유일 | `409 already exists` |

> **버전을 덮어쓸 수 없다.** 같은 버전으로 재업로드하려면 새 버전 문자열을 쓴다. 이미 배포된 버전의 내용이 조용히 바뀌는 것을 막기 위한 의도된 제약이다.

---

## 2. Job에서 선언하기

Job은 소비할 아티팩트를 `consumes_artifacts`에 `{alias, name}` 목록으로 선언한다. **선언하지 않은 아티팩트는 step에서 보이지 않는다.**

### 웹 UI

**Builder** → Job 메타 영역의 **Consumes artifacts (optional)** → `+ Add`로 행을 추가하고 alias와 아티팩트 이름을 입력한다. 입력하면 바로 아래에 step이 받게 될 `ARTIFACT_<ALIAS>_PATH` 목록이 미리 표시된다.

### REST

```bash
curl -X POST http://localhost:8000/api/jobs \
  -H 'Content-Type: application/json' \
  -d '{
    "id": "deploy-app",
    "name": "Deploy App",
    "owner": "ops",
    "consumes_artifacts": [
      {"alias": "jar",  "name": "myapp"},
      {"alias": "conf", "name": "myapp-config"}
    ],
    "steps": [
      {"id": "deploy", "cmd": ["/bin/bash", "deploy.sh"], "timeout": 300, "deps": []}
    ]
  }'
```

### alias 규칙

| 규칙 | 설명 |
|---|---|
| `^[A-Za-z][A-Za-z0-9_]*$` | 영문자로 시작, 영문·숫자·`_`만. `-`와 `.`는 불가 |
| 대소문자 무시 중복 금지 | `jar`와 `JAR`를 함께 선언할 수 없다 |
| 개수 제한 없음 | 필요한 만큼 선언할 수 있다 |

---

## 3. step에서 사용하기

선언한 alias 하나마다 아래 5개 환경변수가 **모든 step**에 주입된다.

| 환경변수 | 값 예시 |
|---|---|
| `ARTIFACT_<ALIAS>_PATH` | `/…/storage/artifacts/ab/myapp-v1.2.0.jar` |
| `ARTIFACT_<ALIAS>_NAME` | `myapp` |
| `ARTIFACT_<ALIAS>_VERSION` | `v1.2.0` |
| `ARTIFACT_<ALIAS>_SHA256` | `ab12…` |
| `ARTIFACT_<ALIAS>_REF` | `uploads://myapp@v1.2.0` |

`<ALIAS>`는 **대문자로 변환**된다. `jar`로 선언했으면 `ARTIFACT_JAR_PATH`다.

위 예시 Job의 `deploy.sh`는 이렇게 쓴다.

```bash
#!/usr/bin/env bash
set -euo pipefail

echo "배포 대상: $ARTIFACT_JAR_REF (sha256=$ARTIFACT_JAR_SHA256)"

# 파일은 읽기 전용이므로 작업 위치로 복사해서 쓴다
cp "$ARTIFACT_JAR_PATH" ./app.jar
cp "$ARTIFACT_CONF_PATH" ./application.yml

java -jar ./app.jar --spring.config.location=./application.yml
```

실행 로그의 각 step 앞부분에는 `artifacts · uploads://myapp@v1.2.0 · uploads://myapp-config@v7`처럼 그 step이 받은 참조가 그대로 찍힌다.

### ⚠️ `cmd`에 `$ARTIFACT_*`를 직접 쓸 수 없다

step은 `shell=False`로 실행된다(`subprocess.Popen(argv)`). argv 원소는 셸 확장을 거치지 않으므로 아래는 **동작하지 않는다.**

```json
"cmd": ["cp", "$ARTIFACT_JAR_PATH", "./app.jar"]
```

`$ARTIFACT_JAR_PATH`가 그 7글자 문자열 그대로 `cp`에 전달된다. 환경변수는 **step이 실행하는 프로그램 안에서** 읽어야 한다. 위 예시처럼 스크립트로 감싸거나, 환경변수를 직접 읽는 프로그램을 쓴다.

```json
"cmd": ["/bin/bash", "deploy.sh"]
```

### ⚠️ step 명령은 allowlist에 있어야 한다

`/bin/bash`는 기본 allowlist에 **없다.** 스크립트로 아티팩트를 다루려면 `backend/app/dev/allowlist.yaml`에 추가하고 백엔드를 재시작해야 하며, 그렇지 않으면 Job 저장 시 `argv not in allowlist: /bin/bash`로 거부된다. allowlist에 명령을 추가하는 것은 워커에 그 실행 권한을 주는 명시적 동의다 — [Security](./security.md) 참고.

### 그 외 주의할 점

- **파일은 0444로 잠겨 있다.** 제자리에서 수정하거나 압축을 풀 수 없으므로 필요하면 복사한 뒤 다루어야 한다.
- **step의 `env`로 `ARTIFACT_*`를 덮어쓸 수 없다.** `ARTIFACT_*`는 step env보다 나중에 병합되며, 덮어쓰기를 시도하면 실행 로그에 `step env ignored for reserved keys: …` 경고가 남는다. Run 기록에 고정된 버전과 실제로 배포된 파일이 어긋나는 것을 막기 위한 장치다.
- **step의 기본 작업 디렉터리는 `storage/runtime`이다.** `deploy.sh`처럼 상대 경로로 스크립트를 실행하려면 그 디렉터리에 파일이 있어야 하거나, step의 `cwd`를 지정해야 한다.

---

## 4. 실행 시 버전 고르기

### 기본: 최신 버전

`artifact_refs`를 주지 않으면 선언된 모든 alias가 `@latest`로 해석된다.

```bash
curl -X POST http://localhost:8000/api/jobs/deploy-app/runs -d '{}'
```

> **`latest`는 "가장 최근에 업로드된 것"이다.** 버전 문자열을 비교해 고르는 것이 아니다. `v2.0.0`을 올린 뒤 `v1.9.0`을 올리면 `latest`는 `v1.9.0`이 된다.

### 명시적으로 버전 고정

alias별로 참조를 지정한다. 일부만 지정해도 되고, 나머지는 `@latest`로 채워진다.

```bash
curl -X POST http://localhost:8000/api/jobs/deploy-app/runs \
  -H 'Content-Type: application/json' \
  -d '{
    "artifact_refs": {
      "jar": "uploads://myapp@v1.1.0"
    }
  }'
```

참조 형식은 `uploads://<name>@<version|latest>`다. alias 키는 **대소문자를 구분하지 않는다** — `jar` 선언에 `JAR`로 보내도 된다.

빈 문자열을 보내면 `@latest`로 대체되지 않고 `INVALID_ARTIFACT`로 거부된다. 참조를 계산해서 넘기는 자동화가 빈 값을 만들었을 때, 의도하지 않은 버전이 조용히 배포되는 것보다 실패하는 편이 안전하기 때문이다.

MCP에서도 동일하다.

```
run_job(job_id="deploy-app", mode="sync", artifact_refs={"jar": "uploads://myapp@v1.1.0"})
```

### 고정(pinning)의 의미

Run이 시작될 때 **한 번만** 해석하고, 그 결과를 Run 레코드에 남긴다.

```json
{
  "artifact_refs": {
    "jar":  {"ref": "uploads://myapp@v1.2.0", "sha256": "ab12…"},
    "conf": {"ref": "uploads://myapp-config@v7", "sha256": "cd34…"}
  }
}
```

여기서 두 가지가 보장된다.

- 실행 중에 누군가 새 버전을 업로드해 `latest` 포인터가 움직여도, 그 Run의 모든 step은 같은 버전을 본다
- 몇 달 뒤 감사할 때 `@latest`가 아니라 **구체적인 버전과 sha256**이 남아 있어 어떤 빌드가 배포됐는지 특정할 수 있다

SSE `run.started` 이벤트에도 고정된 참조가 함께 실린다.

---

## 5. 오류 코드

| 코드 | REST | 의미 | 대응 |
|---|---|---|---|
| `NOT_FOUND` | 404 | 참조한 아티팩트가 없음 | 이름·버전 확인, 업로드 여부 확인 |
| `NOT_READY` | 409 | 아티팩트가 `READY`가 아님 | `READY`가 될 때까지 대기 |
| `UNKNOWN_ALIAS` | 400 | Job이 선언하지 않은 alias를 전달 | Job의 `consumes_artifacts` 확인 |
| `MISMATCH` | 400 | 참조가 선언된 이름과 다른 아티팩트를 가리킴 | alias와 참조의 이름을 일치시킨다 |
| `INVALID_ARTIFACT` | 400 | 참조 형식 오류 · 빈 참조 · alias 중복 전달 | `uploads://<name>@<ver>` 형식 확인 |

오류 응답 본문은 `{"detail": {"error": "<코드>", "message": "<설명>"}}` 형태이고, 실패한 트리거는 감사 로그에 `result=DENY`로 남는다.

Run이 트리거된 뒤 실행 직전에 아티팩트가 사라진 경우, Run은 `RUNNING`으로 방치되지 않고 즉시 `FAILED`로 종료된다.

---

## 6. 자주 겪는 상황

**Q. `ARTIFACT_JAR_PATH`가 step에 안 들어온다**
Job의 `consumes_artifacts`에 alias가 선언돼 있는지 확인한다. 업로드만 해두고 Job에서 선언하지 않으면 step에는 아무것도 주입되지 않는다.

**Q. 같은 버전으로 다시 올리고 싶다**
불가능하다(`409`). 새 버전 문자열을 쓴다.

**Q. 아티팩트를 지우고 싶다**
현재 삭제 API가 없고 자동 정리(prune)도 동작하지 않는다. `storage/artifacts/` 아래 파일은 계속 누적되므로 용량 관리는 별도로 해야 하고, 파일을 직접 지우면 DB 행이 남아 `NOT_FOUND`가 아니라 실행 중 파일 접근 실패로 나타난다.

**Q. `SCANNING` 상태는 언제 생기나**
현재 구현은 바이러스 스캔이 stub이라 업로드 즉시 `READY`가 된다. `NOT_READY`/`SCANNING` 경로는 실제 스캐너를 붙였을 때를 위해 준비된 것이다.

**Q. Job 하나에 아티팩트를 몇 개까지 붙일 수 있나**
제한이 없다. alias만 서로 다르면 된다.

---

## 관련 문서

- [Getting Started](./getting-started.md) — 설치와 첫 Job 만들기
- [REST API](./rest-api.md) — 엔드포인트 전체 목록
- [MCP API](./mcp-api.md) — Agent 도구와 scope
- [Security](./security.md) — allowlist, 시크릿 마스킹, 감사 로그
