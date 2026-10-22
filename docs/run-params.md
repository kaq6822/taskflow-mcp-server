# Run 파라미터 가이드

**🌐 Language / 언어:** [한국어](./run-params.md) · [English](./run-params.en.md)

빌드할 브랜치·배포 대상처럼 **실행할 때마다 달라지는 값**을 Job 정의를 고치지 않고 넘기는 방법이다.

```
① Job에서 선언             ② 실행 시 값 전달            ③ step에서 사용
┌──────────────────────┐  ┌───────────────────────┐  ┌──────────────────────┐
│ params: [{           │  │ params:               │  │ $PARAM_BRANCH        │
│   name: "branch",    │─▶│   {"branch":          │─▶│ = "feature/x"        │
│   default: "dev",    │  │    "feature/x"}       │  │                      │
│   pattern: "…"}]     │  └───────────────────────┘  └──────────────────────┘
└──────────────────────┘             │
                        Run에 고정: params: {"branch": "feature/x"}
```

아티팩트 alias와 같은 원칙을 따른다. **선언하지 않은 이름은 받지 않고**, 해석된 값은 Run에 한 번 고정되며, step `env`로 덮어쓸 수 없다.

---

## 1. Job에서 선언하기

| 필드 | 필수 | 설명 |
|---|---|---|
| `name` | ✅ | `^[A-Za-z][A-Za-z0-9_]*$`. step은 대문자로 바꾼 `PARAM_<NAME>`으로 받는다. 대소문자 무시 중복 금지 |
| `default` | | 생략한 실행에 쓰일 값. **`null`이면 필수 파라미터**가 된다 |
| `pattern` | | Python 정규식. 값 **전체**와 일치해야 한다(`fullmatch`). `default`도 이 패턴을 통과해야 저장된다 |

> **`pattern`을 생략하면 실행 권한(`run:<job_id>`)만 가진 호출자도 공백·`-`로 시작하는 값 등 임의 문자열을 넣을 수 있다.** 서버가 공통으로 막는 것은 빈 값·제어문자(개행 포함)·유효하지 않은 UTF-8·1024자 초과뿐이다. 값이 명령의 인자로 들어가면 패턴을 꼭 지정하고, 앞에 `-`가 오지 않게 하라(예시처럼 첫 글자를 제한). 스크립트에서는 항상 `"$PARAM_X"`로 따옴표를 친다.

```bash
curl -X POST http://localhost:8000/api/jobs \
  -H 'Content-Type: application/json' \
  -d '{
    "id": "be-deploy",
    "name": "Backend deploy",
    "owner": "ops",
    "params": [
      {"name": "branch", "default": "dev", "pattern": "[A-Za-z0-9._][A-Za-z0-9._/-]*"}
    ],
    "steps": [
      {"id": "deploy", "cmd": ["/bin/bash", "/opt/deploy/backend.sh"], "timeout": 900, "deps": []}
    ]
  }'
```

웹 UI에서는 **Builder → Run params (optional)** 에서 이름 · 기본값 · 패턴을 입력한다. 기본값 칸을 비우면 필수가 된다.

## 2. 실행 시 값 넘기기

생략한 파라미터는 기본값을 쓴다. 이름은 대소문자를 구분하지 않는다(`BRANCH`로 보내도 된다).

```bash
# REST
curl -X POST http://localhost:8000/api/jobs/be-deploy/runs \
  -H 'Content-Type: application/json' -d '{"params": {"branch": "feature/x"}}'
```

```
# MCP
run_job(job_id="be-deploy", mode="async", params={"branch": "feature/x"})
```

웹 UI에서는 파라미터를 선언한 Job의 **▷ 실행**을 누르면 값 입력 창이 뜬다. 기본값이 미리 채워져 있다. Step 로그 화면의 **재실행**은 그 Run이 썼던 값으로 창을 연다.

## 3. step에서 사용하기

`cmd`는 `shell=False`라 argv에 `$PARAM_BRANCH`를 써도 확장되지 않는다. **스크립트 안에서 환경변수로 읽는다.**

```bash
#!/usr/bin/env bash
set -euo pipefail
: "${PARAM_BRANCH:?}"
git check-ref-format --branch "$PARAM_BRANCH" >/dev/null   # 패턴 위에 한 번 더
git fetch origin "$PARAM_BRANCH"
git checkout -B build "origin/$PARAM_BRANCH"
```

각 step 로그 앞부분에 `params · PARAM_BRANCH=feature/x`가 찍힌다. **값이 로그와 Run 기록에 그대로 남으므로 비밀값을 파라미터로 넘기지 않는다.**

## 4. 오류 코드

| 코드 | REST | 의미 |
|---|---|---|
| `UNKNOWN_PARAM` | 400 | Job이 선언하지 않은 이름을 전달 |
| `INVALID_PARAM` | 400 | 기본값 없는 파라미터 누락 · `pattern` 불일치 · 문자열 아님 · 빈 값 · 제어문자 포함 · 유효하지 않은 UTF-8 · 1024자 초과 · 같은 이름 중복 전달 |

거부된 트리거는 Run을 만들지 않고 감사 로그에 `result=DENY`로 남는다. 파라미터를 선언하지 않은 Job에 `params`를 보내도 `UNKNOWN_PARAM`이다 — 조용히 무시되지 않는다.
