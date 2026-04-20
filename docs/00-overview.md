# TaskFlow MCP Server — 프로젝트 개요

## 1. 한 줄 요약

**TaskFlow**는 Workflow(여러 Step의 DAG)로 Job을 정의하고, 수동/스케줄/**MCP(AI Agent) 트리거**로 실행하며, 실시간 진행 · 실패 진단 · 배포 아티팩트 · 감사 로그까지 단일 시스템에서 다룰 수 있는 **Workflow 오케스트레이션 플랫폼**이다. AI Agent가 안전하게 빌드·배포·운영 Job을 실행할 수 있도록 MCP 프로토콜 기반의 Key·scope·rate-limit 통제를 제공한다.

## 2. 핵심 타깃 사용자

- **주 페르소나:** AI Agent 개발자 (MCP 사용자)
  - AI Agent(예: Claude)를 통해 빌드·배포·운영 자동화를 구축하는 개발자.
  - CLI/DevOps 도구에 익숙하며, Agent가 안전한 범위 내에서만 작업하도록 통제하는 것이 핵심 관심사.
- **부가 페르소나:** DevOps / SRE
  - 주기적인 배포 · ETL · 백업 · 리포트 Job을 정의/운영.

## 3. 제품 포지셔닝

TaskFlow는 다음 3가지 축을 동시에 만족해야 한다:

| 축 | 요구 수준 | 설명 |
|---|---|---|
| **실행 오케스트레이션** | Airflow/Argo 수준 | DAG · 재시도 · 타임아웃 · 롤백 정책 |
| **관측성(Observability)** | 핵심 지원 | 실시간 로그 · 진행률 · 실패 진단 |
| **AI Agent 연동(MCP)** | 핵심 지원 | Key 발급/회전/revoke · scope 기반 권한 · 호출 감사 · 실행 대기 계약 |

## 4. 주요 유즈케이스

### 4.1 AI Agent 주도 배포 (Primary)

개발자가 AI Agent와 코드 작업 → Agent가 `/deploy` skill command 실행 → 빌드 산출물을 TaskFlow에 업로드 → 배포 Job 실행 → 결과를 개발자에게 피드백.

이 플로우의 상세 계약은 [`02-business-rules.md §10`](./02-business-rules.md)과 [`03-system-spec.md §5`](./03-system-spec.md)에 정의되어 있다.

### 4.2 주기적 ETL/백업 (Schedule-driven)

cron 트리거로 매일 야간 ETL을 실행, 실패 시 감사 로그에 기록되고 운영자가 로그 뷰어에서 진단.

### 4.3 수동 운영 배포 (Human-driven)

운영자가 UI에서 직접 Job을 실행 → 실시간 진행 관찰 → 실패 시 "from failed 재실행".

### 4.4 배포 아티팩트 수명관리

CI/Agent가 빌드 산출물(.tar.gz/.jar/.zip)을 TaskFlow에 업로드 → 특정 Job이 해당 아티팩트를 읽기 전용으로 마운트하여 소비.

## 5. 범위 (Scope)

### 5.1 In-scope

- Job/Workflow 정의 (DAG, argv-based Step)
- Run 실행 엔진 (Worker pool, 시간대/의존성/타임아웃/재시도)
- 실시간 로그 스트림 · 실패 진단
- 배포 아티팩트 관리 (버전 · 해시 · 서명 · 소비 Job 추적)
- MCP 엔드포인트 (Key, scope, rate-limit)
- 불변 감사 로그 (hash-chained, SIEM forward)

### 5.2 Out-of-scope (비목표)

- 복잡한 RBAC/ABAC 권한 매트릭스 (scope 기반으로 단순화)
- 파일 업로드의 범용 사용 — **오직 "배포 아티팩트"로만** 한정
- 워크플로우 버전 관리 시스템 (YAML import/export로 위임)
- 알림 채널 구성 시스템 (Step의 notify cmd로 표현)
- Multi-tenant / Multi-workspace

## 6. 디자인 핸드오프 출처

- 디자인 원본: Claude Design 핸드오프 번들
- 주 파일: `TaskFlow Prototype.html` (hi-fi 클릭 가능 프로토타입)
- 디자인 의사결정 기록: `chats/chat1.md`

> UI/UX 시각적 세부 사항은 프로토타입의 `proto/theme.css`, `proto/**/*.jsx`, `TaskFlow Prototype.html`을 단일 진실로 삼는다. 본 문서 집합은 **제품 레벨의 골 · 규칙 · 스펙**만 다룬다.

## 7. 문서 구성

| 파일 | 목적 |
|---|---|
| `00-overview.md` | 본 문서. 프로젝트 조감 · 범위 |
| `01-design-goals.md` | 제품 레벨의 디자인 골 · 원칙 · 제약 |
| `02-business-rules.md` | 도메인 규칙 · 상태 전이 · MCP Agent 플로우 · 정책 |
| `03-system-spec.md` | 시스템 아키텍처 · MCP 인터페이스 · 실행 대기 계약 |
