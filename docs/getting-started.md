# Getting Started

TaskFlow를 처음 실행하고 UI에서 첫 Job을 만드는 과정을 5분 안에 따라갈 수 있는 가이드입니다.

## 요구사항

- Python 3.11 이상 (3.14에서도 검증됨)
- Node.js 20 이상, npm 10 이상
- macOS · Linux (Windows는 WSL 권장)

## 설치

```sh
git clone <this-repo> taskflow-mcp-server
cd taskflow-mcp-server
cp .env.example .env      # 기본값이 적절하므로 보통 수정 불필요
make setup
```

`make setup`이 수행하는 일:

1. `backend/.venv` 파이썬 가상환경 생성
2. `pip install -e "backend[dev]"` — FastAPI · SQLAlchemy · `mcp` SDK · pytest 등 설치
3. `cd frontend && npm install` — React 등 프론트엔드 의존성 설치
4. `alembic upgrade head` — `backend/taskflow.db` 스키마 생성

빈 DB로 시작합니다. seed 데이터는 투입되지 않습니다.

## 실행

```sh
make dev
```

두 프로세스가 동시에 뜹니다:

| 프로세스 | 포트 | 역할 |
|---|---|---|
| Backend (`python -m app`) | `http://localhost:8000` | REST API · SSE |
| | `http://localhost:7391/mcp` | MCP 엔드포인트 (Bearer 인증) — Backend와 같은 프로세스 |
| Frontend | `http://localhost:5173` | React UI (API는 Vite 프록시) |

브라우저로 **http://localhost:5173** 접속. 첫 실행 시 Backend가 admin 세션 토큰을 한 번 콘솔에 출력합니다 (향후 UI 인증 활성화용).

> Vite 기본 설정은 `localhost`에만 바인드합니다. 원격 접근이나 LAN 공유가 필요하면 [Operations](./operations.md)의 네트워크 바인딩 섹션을 참조.

## 첫 번째 Job 만들기

![Workflow Builder](./assets/03-builder.png)

1. Dashboard → `+ 새 Job`
2. Builder에서 다음을 입력
   - **ID**: `hello` (kebab-case, 소문자)
   - **Name**: `Hello Demo`
   - **Step 1** (기본으로 들어 있는 `greet`): argv = `["echo", "hello from taskflow"]`, timeout = 10
   - **Step 2** (`+ Step 추가`로 추가, id `wait`): argv = `["sleep", "1"]`, deps = `greet`, timeout = 5
3. `저장` → Dashboard로 이동
4. `hello` 행의 `▷ 실행` 클릭
5. Topbar에 `LIVE` 칩 표시 → Monitor 화면에서 실제 stdout이 SSE로 스트림됨
6. 완료 후 Audit 화면에서 `job.create`, `job.run`, `job.run.done` 이벤트 확인 가능

## Step 작업 디렉토리 (`cwd`)

Step은 기본적으로 `TASKFLOW_STEP_CWD`(`./storage/runtime`)에서 실행됩니다. 특정 디렉토리에서 실행해야 하는 배포 Job은 Step에 `cwd`를 지정하세요.

```json
{
  "id": "deploy",
  "cwd": "/opt/taskflow/apps/api",
  "cmd": ["./deploy.sh"],
  "timeout": 300,
  "deps": []
}
```

`cd /opt/taskflow/apps/api`를 별도 Step으로 두는 방식은 지원하지 않습니다. `cd`는 다음 Step의 작업 디렉토리를 바꾸지 못하므로 `cwd` 필드로 표현합니다.

## 출력 기반 성공/실패 판정

기본 성공 조건은 여전히 `exit_code == 0`입니다. 추가로 stdout/stderr에 특정 문자열이 포함되는지 검사하려면 Step에 `success_contains` 또는 `failure_contains`를 지정하세요.

```json
{
  "id": "health",
  "cmd": ["curl", "-fsS", "http://127.0.0.1:8080/actuator/health"],
  "success_contains": ["UP"],
  "failure_contains": ["DOWN", "Exception"],
  "timeout": 30,
  "deps": ["deploy"]
}
```

`failure_contains` 중 하나라도 출력에 포함되면 Step은 `FAILED`입니다. `success_contains`는 exit 0 이후 모두 포함되어야 하며, 하나라도 누락되면 `FAILED`입니다.

## 실행 파라미터와 출력값

실행할 때마다 달라지는 값(브랜치 등)은 Job에 **Run 파라미터**로 선언하고, step이 알아낸 값(배포한 커밋 등)은 **출력값**으로 Run에 남길 수 있습니다.

- **Builder → Run params (optional)** — 이름 · 기본값 · 패턴을 입력합니다. 기본값을 비우면 필수 파라미터가 되고, 입력하는 즉시 step이 받게 될 `PARAM_<NAME>` 목록이 표시됩니다.
- **▷ 실행** — 파라미터를 선언한 Job은 실행 전에 값 입력 창이 뜹니다(기본값이 미리 채워짐). 거부된 값은 `INVALID_PARAM` 토스트와 함께 창이 유지됩니다. 파라미터가 없는 Job은 바로 실행됩니다.
- **Step 로그 화면** — 상단 상태 칩 옆에 그 Run이 쓴 파라미터(`branch=…`)와 기록된 출력값(`→ commit=…`)이 칩으로 표시됩니다. **재실행**은 그 Run의 파라미터 값으로 입력 창을 엽니다.
- **Job 상세** — 메타 카드에 선언된 파라미터(`→ PARAM_<NAME>`)가, Runs 표의 `Outputs` 열에 각 Run의 출력값이 보입니다.

step 쪽 사용법은 [Run 파라미터](./run-params.md)와 [Run 출력값](./run-outputs.md)을 참고하세요.

## 다음 단계

- AI Agent에서 호출하려면 → [MCP API](./mcp-api.md)
- REST/SSE로 직접 다루려면 → [REST API](./rest-api.md)
- 프로덕션 배포/네트워크 바인딩 → [Operations](./operations.md)
- 설계 배경/도메인 규칙 → [00-overview.md](./00-overview.md) → [03-system-spec.md](./03-system-spec.md)
