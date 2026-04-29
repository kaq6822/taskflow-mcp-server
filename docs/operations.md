# Operations

실행 모드, 네트워크 바인딩, 프로덕션 릴리즈, 환경변수, DB/스토리지 관리까지 운영자가 알아야 하는 내용을 모았습니다.

## 실행 모드

3가지 중 하나를 고르세요. **프로덕션 배포는 B 또는 C**입니다.

### A. 로컬 개발 (hot-reload)

```sh
make dev
```

세 프로세스가 동시에 뜹니다:

| 프로세스 | 포트 | 역할 |
|---|---|---|
| Backend | `http://localhost:8000` | REST API · SSE |
| MCP Server | `http://localhost:7391/mcp` | MCP 엔드포인트 (Bearer 인증) |
| Frontend | `http://localhost:5173` | React UI (API는 Vite 프록시) |

### B. 프로덕션 (foreground)

```sh
make setup        # 1회
make build        # frontend/dist 생성
make start        # backend가 SPA+API 통합 서빙(:8000), mcp(:7391) 별도
```

접속: `http://localhost:8000` (Vite 불필요, same-origin이라 CORS 이슈 없음). `Ctrl+C`로 정지.

### C. 프로덕션 (background, 로그아웃 후에도 유지)

```sh
make setup
make build
make start-bg     # nohup 기반. logs/{backend,mcp}.pid + logs/taskflow.log 생성
make logs         # tail -f logs/taskflow.log
make status       # running 여부 · pid · port
make stop         # 정지 (pidfile + pkill fallback)
```

포트/바인딩 변경은 `make start-bg API_PORT=80 MCP_PORT=7391` 식으로.

## 주요 명령

| 상황 | 명령 | 비고 |
|---|---|---|
| 최초 설치 | `make setup` | venv · npm · migrate |
| 로컬 dev | `make dev` | Vite는 `localhost`만 바인드 |
| LAN dev | `make dev-lan` | Vite·API·MCP 모두 `0.0.0.0`으로 바인드 |
| 프로덕션 빌드 | `make build` | `frontend/dist` 생성 |
| 프로덕션 실행 | `make start` | backend가 SPA+API 통합 서빙, MCP 분리 |
| 테스트 | `make test` | pytest |
| DB 초기화 | `make reset` | SQLite + storage 삭제 후 migrate |
| 전체 제거 | `make clean` | venv / node_modules / DB |

개별 서비스:

```sh
make dev-backend   # uvicorn app.main:app :8000 (dev)
make dev-mcp       # python -m app.mcp_server :7391 (dev)
make dev-frontend  # vite :5173 (dev)
make start-backend # production: SPA+API 통합
make start-mcp     # production MCP
```

## 네트워크 바인딩

기본 `make dev`는 **개발자 로컬에서만** 접근 가능하도록 Vite를 `localhost`에 바인드합니다. 원격 호스트(같은 LAN 내 다른 기기 등)에서 쓰려면:

```sh
# 1) LAN 바인딩으로 실행
make dev-lan TASKFLOW_CORS_ORIGINS=http://192.168.1.10:5173

# 2) 또는 환경변수로 세밀 제어
TASKFLOW_FRONTEND_HOST=0.0.0.0 \
TASKFLOW_API_HOST=0.0.0.0 \
TASKFLOW_MCP_HOST=0.0.0.0 \
TASKFLOW_API_HOST_PUBLIC=192.168.1.10 \
TASKFLOW_CORS_ORIGINS=http://192.168.1.10:5173 \
  make dev
```

- `TASKFLOW_FRONTEND_HOST` — Vite 바인딩 인터페이스
- `TASKFLOW_API_HOST` / `TASKFLOW_MCP_HOST` — FastAPI / MCP 바인딩 인터페이스
- `TASKFLOW_API_HOST_PUBLIC` — 브라우저/외부 클라이언트가 API에 접근할 때 쓰는 호스트 (Vite proxy target 구성용)
- `TASKFLOW_CORS_ORIGINS` — **콤마 구분** origin 화이트리스트. 원격 브라우저가 `/api`를 직접 호출할 때 반드시 포함. Vite 프록시 경유 호출은 same-origin이라 CORS 영향 없음. dev에서 `*` 한 개만 넣으면 allow-all.

> ⚠️ UI에는 현재 로그인 게이트가 없습니다. `dev-lan`으로 외부 노출 시 누구나 Job 생성/실행이 가능하므로 신뢰된 네트워크에서만 사용하세요.

## 프로덕션 릴리즈

`make start`는 다음을 수행합니다:

1. Backend(uvicorn) 한 포트에서 **API + 빌드된 SPA**를 동시 서빙 — 별도 Vite 프로세스 불필요, CORS 이슈 자연 제거 (same-origin).
2. MCP 서버는 기존처럼 7391 포트에서 독립 실행.
3. `TASKFLOW_ENV=production`으로 설정되어 CORS가 `TASKFLOW_CORS_ORIGINS`에 지정된 항목으로 고정됨 (`*`는 안전을 위해 production에서 자동 제거).

릴리즈 파이프라인 예:

```sh
# 1) 빌드
make build                       # frontend/dist 생성

# 2) 환경 설정 (.env 예시)
# TASKFLOW_ENV=production
# TASKFLOW_API_PORT=80
# TASKFLOW_MCP_PORT=7391
# TASKFLOW_CORS_ORIGINS=https://taskflow.example.com
# TASKFLOW_FRONTEND_DIST_DIR=../frontend/dist

# 3) 실행 (필요시 systemd / pm2 / Docker 등에 래핑)
make start API_PORT=80

# 또는 수동으로
TASKFLOW_ENV=production \
TASKFLOW_FRONTEND_DIST_DIR=../frontend/dist \
  ./backend/.venv/bin/uvicorn app.main:app --host 0.0.0.0 --port 80

TASKFLOW_ENV=production \
  ./backend/.venv/bin/python -m app.mcp_server
```

리버스 프록시(Nginx/Caddy)를 쓰는 경우 `/`와 `/api/*`를 backend 포트로, `/mcp`를 MCP 포트로 각각 프록시하면 됩니다. HTTPS 종단도 리버스 프록시 계층에서 처리하는 것을 권장.

## 환경변수 참조

| 변수 | 기본값 | 설명 |
|---|---|---|
| `TASKFLOW_ENV` | `dev` | `dev` \| `production` |
| `TASKFLOW_DB_URL` | `sqlite+aiosqlite:///./taskflow.db` | DB URL |
| `TASKFLOW_STORAGE_DIR` | `./storage` | 아티팩트·로그 루트 |
| `TASKFLOW_STEP_CWD` | `./storage/runtime` | Step `cwd` 미지정 시 사용할 기본 subprocess cwd |
| `TASKFLOW_API_HOST` / `TASKFLOW_API_PORT` | `0.0.0.0` / `8000` | Backend 바인딩 |
| `TASKFLOW_MCP_HOST` / `TASKFLOW_MCP_PORT` | `0.0.0.0` / `7391` | MCP 바인딩 |
| `TASKFLOW_MCP_MAX_SYNC_SEC` | `600` | `run_job(sync)` 최대 대기 |
| `TASKFLOW_FRONTEND_HOST` / `TASKFLOW_FRONTEND_PORT` | `localhost` / `5173` | Vite 바인딩 |
| `TASKFLOW_API_HOST_PUBLIC` | `localhost` | 외부에서 본 API 호스트 (Vite proxy target) |
| `TASKFLOW_CORS_ORIGINS` | `http://localhost:5173,http://127.0.0.1:5173` | 콤마 구분 origin 화이트리스트 |
| `TASKFLOW_FRONTEND_DIST_DIR` | *(unset)* | production 모드의 SPA dist 경로 |
| `TASKFLOW_ALLOWLIST_PATH` | `./app/dev/allowlist.yaml` | argv allowlist 경로. 프로덕션은 `/etc/taskflow/allowlist.yaml` 같은 저장소 밖 경로 권장 |

## Step cwd 관리

Step은 기본적으로 `TASKFLOW_STEP_CWD`에서 실행됩니다. 특정 배포 Job처럼 실행 디렉토리가 필요한 경우 Builder 또는 REST Job 정의에서 Step별 `cwd`를 지정하세요.

```json
{
  "id": "deploy",
  "cwd": "/opt/taskflow/apps/api",
  "cmd": ["./deploy.sh"],
  "timeout": 300
}
```

명시적 `cwd`는 실행 전에 이미 존재하는 디렉토리여야 합니다. 존재하지 않거나 파일이면 해당 Step은 `FAILED`가 됩니다. 운영 배포에서는 상대 경로보다 절대 경로를 권장합니다.

`cd /path`를 별도 Step으로 두는 방식은 지원하지 않습니다. `cd`는 shell/process 상태 변경이라 다음 Step에 전달되지 않으며, TaskFlow는 이를 `policy.violation`으로 거부합니다.

## argv allowlist 관리

argv allowlist는 **환경별** 설정입니다:

| 경로 | 추적 | 용도 |
|---|---|---|
| `backend/app/dev/allowlist.example.yaml` | git 추적 | 저장소 공유 템플릿 (변경은 PR로 리뷰) |
| `backend/app/dev/allowlist.yaml` | `.gitignore` 제외 | `make setup`이 자동 복사하는 로컬 사본. 실제 운영 중 사용 |
| `TASKFLOW_ALLOWLIST_PATH`로 지정한 경로 | — | 프로덕션 권장. `/etc/taskflow/allowlist.yaml` 등 저장소 밖 파일 |

첫 설치 후 `allowlist.yaml`을 본인 환경에 맞게 편집하세요. 변경 후 반영은 backend 재시작(`make stop && make start-bg`)입니다 — 현재 구현은 런타임 hot-reload를 지원하지 않으므로 로그 상에 "falling back to shipped template" 경고가 보이면 `make bootstrap-allowlist`로 로컬 사본부터 생성하세요.

프로덕션 배포에서는 deployment 도구(Ansible, Terraform, Helm 등)로 `TASKFLOW_ALLOWLIST_PATH`를 세팅하고 해당 경로 파일을 관리하여, 저장소의 템플릿과 완전히 분리된 수명 주기를 유지하는 것을 권장합니다.

## 데이터 위치

| 경로 | 내용 |
|---|---|
| `backend/taskflow.db` | SQLite DB (jobs, runs, audit, keys) |
| `backend/storage/runtime/` | Step 기본 subprocess cwd (`TASKFLOW_STEP_CWD` 기본값) |
| `backend/storage/logs/<run_id>/<step_id>.log` | Step 로그 파일 |
| `backend/storage/artifacts/` | 업로드된 아티팩트 바이너리 |
| `logs/taskflow.log`, `logs/*.pid` | `make start-bg` 로그·PID |

런타임 데이터는 전부 gitignore됩니다. 전체 초기화는 `make reset`.
