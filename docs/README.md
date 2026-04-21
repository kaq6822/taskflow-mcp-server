# TaskFlow MCP Server — 문서

이 폴더는 두 종류의 문서를 담고 있습니다:

1. **사용자/운영자 가이드** — 설치부터 운영까지. README의 링크 대상.
2. **설계 문서** (`00~03`) — 구현 착수 전 합의를 위한 제품 레벨 스펙.

## 사용자 · 운영자 가이드

| 문서 | 다루는 내용 |
|---|---|
| [getting-started.md](./getting-started.md) | 설치 · 첫 Job 만들기 · argv allowlist |
| [mcp-api.md](./mcp-api.md) | Key 발급 · JSON-RPC 호출 · 도구 목록 · Claude Desktop 연동 |
| [rest-api.md](./rest-api.md) | 엔드포인트 · SSE 이벤트 포맷 · 오류 코드 |
| [operations.md](./operations.md) | 실행 모드(A/B/C) · 네트워크 바인딩 · 프로덕션 릴리즈 · 환경변수 |
| [security.md](./security.md) | `shell=False` · allowlist · 시크릿 마스킹 · hash-chained audit |
| [troubleshooting.md](./troubleshooting.md) | 자주 발생하는 증상과 해결 |

## 설계 문서

구현 전 합의를 위한 제품 레벨 문서입니다. 시각적 UI/UX 세부 및 코드베이스에서 직접 확인 가능한 사항(데이터 모델, 화면 구조 등)은 다루지 않습니다.

| # | 파일 | 다루는 내용 |
|---|---|---|
| 00 | [overview.md](./00-overview.md) | 프로젝트 미션 · 페르소나 · 유즈케이스 · 범위/비목표 |
| 01 | [design-goals.md](./01-design-goals.md) | 제품 디자인 원칙 (AI Agent First · Deterministic · Audit 등) · 성공 기준 · 트레이드오프 |
| 02 | [business-rules.md](./02-business-rules.md) | 도메인 규칙 · 상태 전이 · §10 AI Agent End-to-End 플로우 |
| 03 | [system-spec.md](./03-system-spec.md) | 시스템 아키텍처 · §5 MCP Tools · 실행 대기 계약 · 응답 스키마 · 보안/운영 |

## 다루지 않는 것

| 항목 | 참조처 |
|---|---|
| 시각적 UI/UX · 컴포넌트 · 토큰 | 프로토타입(`TaskFlow Prototype.html` + `proto/theme.css`, `proto/**/*.jsx`) |
| 화면별 레이아웃 | 프로토타입의 `proto/screens/*.jsx` |
| 데이터 모델 · 시드 데이터 | 프로토타입의 `proto/store.jsx` (단, 실제 구현은 빈 DB로 시작) |
| 디자인 히스토리 | `chats/chat1.md` (Claude Design 핸드오프 번들) |
