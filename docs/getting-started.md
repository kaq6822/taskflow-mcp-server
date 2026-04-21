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

세 프로세스가 동시에 뜹니다:

| 프로세스 | 포트 | 역할 |
|---|---|---|
| Backend | `http://localhost:8000` | REST API · SSE |
| MCP Server | `http://localhost:7391/mcp` | MCP 엔드포인트 (Bearer 인증) |
| Frontend | `http://localhost:5173` | React UI (API는 Vite 프록시) |

브라우저로 **http://localhost:5173** 접속. 첫 실행 시 Backend가 admin 세션 토큰을 한 번 콘솔에 출력합니다 (향후 UI 인증 활성화용).

> Vite 기본 설정은 `localhost`에만 바인드합니다. 원격 접근이나 LAN 공유가 필요하면 [Operations](./operations.md)의 네트워크 바인딩 섹션을 참조.

## 첫 번째 Job 만들기

![Workflow Builder](./assets/03-builder.png)

1. Dashboard → `+ 새 Job`
2. Builder에서 다음을 입력
   - **ID**: `hello` (kebab-case, 소문자)
   - **Name**: `Hello Demo`
   - **Step 1**: argv = `["echo", "hello from taskflow"]`, timeout = 10
   - **Step 2**: argv = `["sleep", "1"]`, deps = `greet`, timeout = 5
3. `저장` → Dashboard로 이동
4. `hello` 행의 `▷ 실행` 클릭
5. Topbar에 `LIVE` 칩 표시 → Monitor 화면에서 실제 stdout이 SSE로 스트림됨
6. 완료 후 Audit 화면에서 `job.create`, `job.run`, `job.run.done` 이벤트 확인 가능

## argv allowlist

Step의 argv는 `backend/app/dev/allowlist.yaml`에 등록된 커맨드만 사용할 수 있습니다. 기본 허용:

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

필요한 커맨드(예: `npm`, `aws`)는 이 파일에 명시적으로 추가해야 실행됩니다. 이는 사고 방지를 위한 의도된 제한입니다. 정책 배경은 [Security](./security.md) 참조.

## 다음 단계

- AI Agent에서 호출하려면 → [MCP API](./mcp-api.md)
- REST/SSE로 직접 다루려면 → [REST API](./rest-api.md)
- 프로덕션 배포/네트워크 바인딩 → [Operations](./operations.md)
- 설계 배경/도메인 규칙 → [00-overview.md](./00-overview.md) → [03-system-spec.md](./03-system-spec.md)
