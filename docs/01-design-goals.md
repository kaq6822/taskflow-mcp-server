# 디자인 골 (Design Goals)

본 문서는 **제품 레벨의 설계 목표**를 다룬다. 시각적 UI/UX 세부는 다루지 않으며, 그 내용은 프로토타입(`TaskFlow Prototype.html` + `proto/`)을 단일 진실로 본다.

## 1. 제품 미션

**AI Agent를 핵심 실행자로 수용하는 Workflow 오케스트레이션.**

기존 Airflow/Argo가 "human-operator 중심"으로 설계되었다면, TaskFlow는 **AI Agent를 통제된 범위에서 안전하게 실행자로 수용하는 것**을 제품의 1차 가치로 삼는다.

## 2. 페르소나

### 2.1 주 페르소나: AI Agent 개발자 (MCP 사용자)

- **스킬 레벨:** CLI/DevOps 도구(K8s, Airflow, Grafana)에 익숙한 시니어 개발자.
- **핵심 관심사:**
  - Agent가 **얼마나 안전하게 제한된 범위에서만** Job을 실행하는가.
  - Agent의 실행 결과를 **얼마나 빠르고 명확하게** 피드백 받는가.
  - Agent가 일으킨 모든 행위를 **사후 감사 가능한가**.

### 2.2 부가 페르소나: DevOps / SRE

- 주기적인 운영 Job 정의/관리.
- 배포 아티팩트의 버전/해시/서명 추적이 명확해야 함.

## 3. 핵심 설계 원칙

### 3.1 AI Agent First, But Sandboxed

Agent는 제품의 1등 사용자지만, **어떤 Agent도 기본적으로 신뢰하지 않는다.**

- 모든 MCP 호출은 scope 기반으로 **화이트리스트 방식** 권한 검사.
- Rate-limit을 key 단위로 강제.
- Step 실행은 `shell=False` · argv allowlist · `no-root` · 전용 계정으로 고정.
- Agent 행위는 전부 `src=mcp` 로 tagging되어 감사 로그에 기록.

### 3.2 Deterministic, Not Magical

- Workflow는 **declarative DAG**로 표현 (YAML/JSON으로 직렬화 가능).
- Step은 **argv 배열만 허용** — shell 인터폴레이션/eval/스크립트 문자열 금지.
- 같은 입력(Job 정의 + 아티팩트 버전 + 환경변수)에 대해 결과가 재현 가능해야 함.

### 3.3 Observable by Default

- 모든 Run은 Step 단위로 상태/로그/소요시간이 기록됨.
- 실시간 진행 관찰과 사후 탐색이 동일한 데이터 모델에서 가능.
- 실패 시 **heuristic 진단 카드**를 자동 제공 (타임아웃 패턴 · 동일 에러 빈도 등).

### 3.4 Immutable Audit

- 모든 사용자/시스템 행위는 append-only · hash-chained 감사 로그로 기록.
- Audit row는 수정/삭제 불가. 체인 검증으로 tamper-evident.
- 보관 기간 후에는 SIEM으로 forward.

### 3.5 Artifact as the Only Upload Channel

파일 업로드는 **오직 "배포 아티팩트" 시나리오**로 한정:

- 빌드 산출물(`.tar.gz`/`.jar`/`.zip`/`.ipa`)이 업로드 대상.
- 업로드된 아티팩트는 **읽기 전용 · 해시 검증 · 스캔 통과 후에만 소비 가능**.
- Step은 환경변수 `$ARTIFACT` 참조(`uploads://<name>@<ver|latest>`)로만 아티팩트 접근.

> 설정 파일 주입, 입력 CSV 등 범용 업로드는 본 제품의 scope가 아니다. 외부 스토리지 + `params`로 처리.

### 3.6 Single Source of Truth per Run

Run 하나는 다음을 가진 **불변 스냅샷**이 된다:

- Job 정의 snapshot (당시 YAML)
- 사용된 아티팩트 버전 (해시 포함)
- 환경변수 스냅샷 (시크릿은 해시)
- Step별 로그 blob 참조
- 시작/종료 시각, 실행자, 트리거

동일 Run id로 "이 배포가 실제로 무엇을 실행했는가"가 반복 재현될 수 있어야 한다.

## 4. 성공 기준 (Success Criteria)

| 기준 | 측정 |
|---|---|
| AI Agent가 잘못된 Job을 실행할 수 없다 | scope 미매칭 시 100% DENY + audit |
| Agent가 실행 결과를 즉시 받을 수 있다 | `run_job` 완료 응답 지연 ≤ Job timeout + α |
| 운영자가 Agent 행위를 사후 추적 가능 | 모든 MCP 호출이 audit에 `src=mcp` · actor 포함하여 존재 |
| 실패 원인이 한 화면에서 파악됨 | 실패 Run 선택 → 진단 카드까지 ≤ 1 클릭 |
| 아티팩트의 "어느 버전이 어디에 배포되었는가" 추적 | Artifact ↔ Run ↔ 소비 Job 3-way 참조가 DB에 존재 |

## 5. 제약 · 비목표 (Non-goals)

### 5.1 제약

- **권한 전용 화면 없음** — scope/정책은 Job 상세의 정책 칩 · Step 설정 · Audit으로 분산 표현.
- **파일 업로드 = 배포 아티팩트 한정**.
- **Multi-tenant 아님** — 단일 워크스페이스 가정.
- **동시성 1 (기본)** — Job별 동시 Run은 기본 1개. 명시적으로 올려야 함.

### 5.2 비목표

- RBAC/ABAC 매트릭스 UI
- Workflow 버전 관리 시스템 (GitOps로 위임)
- 알림 채널 구성 시스템
- 분산 Worker 간 복잡한 리소스 스케줄링 (단순 FIFO + concurrency cap)

## 6. 트레이드오프 결정

| 결정 | 대안 | 선택 이유 |
|---|---|---|
| **argv 배열 only (shell=False)** | 자유 shell 문자열 | 주입 공격 차단 · 재현 가능성 · 감사 용이 |
| **아티팩트 읽기 전용 mount** | 쓰기 가능 volume | 배포물 무결성 보장 |
| **scope 기반 단순 권한** | RBAC 매트릭스 | Agent use-case에 과잉 설계 방지 |
| **동시성 기본 1** | N 동시 실행 | 배포·ETL 등 멱등성 없는 Job이 대부분 |
| **append-only audit** | soft-delete | 규정 준수 · tamper-evident |
| **30일 audit 보관 + SIEM forward** | 영구 보관 | 스토리지 비용 · SIEM이 장기 보관 책임 |
