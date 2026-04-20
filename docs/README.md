# TaskFlow MCP Server — 설계 문서 (docs/)

이 폴더는 구현 착수 전 합의를 위한 **제품 레벨 문서**입니다. 시각적 UI/UX 세부 및 코드베이스에서 확인 가능한 사항(데이터 모델, 화면 구조 등)은 다루지 않습니다.

## 읽는 순서

| # | 파일 | 다루는 내용 |
|---|---|---|
| 00 | [overview.md](./00-overview.md) | 프로젝트 미션 · 페르소나 · 유즈케이스 · 범위/비목표 |
| 01 | [design-goals.md](./01-design-goals.md) | 제품 디자인 원칙 (AI Agent First · Deterministic · Audit 등) · 성공 기준 · 트레이드오프 |
| 02 | [business-rules.md](./02-business-rules.md) | 도메인 규칙 · 상태 전이 · **§10 AI Agent End-to-End 플로우** |
| 03 | [system-spec.md](./03-system-spec.md) | 시스템 아키텍처 · **§5 MCP Tools · 실행 대기 계약 · 응답 스키마** · 보안/운영 |

## 다루지 않는 것

| 항목 | 참조처 |
|---|---|
| 시각적 UI/UX · 컴포넌트 · 토큰 | 프로토타입(`TaskFlow Prototype.html` + `proto/theme.css`, `proto/**/*.jsx`) |
| 화면별 레이아웃 | 프로토타입의 `proto/screens/*.jsx` |
| 데이터 모델 · 시드 데이터 | 프로토타입의 `proto/store.jsx` |
| 디자인 히스토리 | `chats/chat1.md` (Claude Design 핸드오프 번들) |

## 다음 단계

1. 본 문서들을 팀과 리뷰하여 스코프/용어를 확정
2. Backend API 계약(OpenAPI) · MCP tool 정의를 본 문서 기반으로 작성
3. Worker 실행 정책(allowlist, shell=False, no-root) 구현
4. Frontend는 프로토타입을 단일 진실로 삼아 구현
