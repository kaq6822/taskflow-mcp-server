# Run 출력값 가이드

**🌐 Language / 언어:** [한국어](./run-outputs.md) · [English](./run-outputs.en.md)

step이 실행 중에 알아낸 값 — 실제로 빌드한 커밋, 만든 버전 등 — 을 **Run 기록에 남기는** 방법이다. [Run 파라미터](./run-params.md)가 "들어가는 값"이라면 출력값은 "나온 값"이다.

## 1. step에서 남기기

stdout에 한 줄을 찍는다.

```bash
echo "::output commit=$(git rev-parse HEAD)"
echo "::output branch=$PARAM_BRANCH"
```

| 규칙 | 내용 |
|---|---|
| 위치 | **stdout**, 줄 맨 앞이 `::output ` 로 시작. stderr의 같은 줄은 무시한다 |
| key | `^[A-Za-z][A-Za-z0-9_]*$` |
| value | `=` 뒤 나머지 전부(뒤의 `\r` 제외). 빈 값·앞뒤 공백·제어문자(C0/C1·U+2028/2029)·깨진 문자(U+FFFD)·1024자 초과는 무시하고 로그에 `output ignored` 경고를 남긴다 |
| 덮어쓰기 | 같은 key를 다시 찍으면(같은 step·뒤 step) 나중 값이 남고, 값이 바뀌면 로그에 `overwritten` 경고를 남긴다 |
| 실패한 step | **SUCCESS로 끝난 step의 값만 기록한다.** 실패·타임아웃·취소된 step의 값은 버리고 `outputs discarded` 경고를 남긴다 — `CONTINUE`·`RETRY`로 Run이 성공해도 실패한 시도의 값이 섞이지 않는다 |

출력값은 step의 마지막 부분에서 찍는 것이 안전하다. 그 뒤에 임의 내용(커밋 메시지, 파일 내용 등)을 stdout으로 흘리면 그 안의 `::output` 줄이 값을 덮어쓸 수 있다.

step 로그에는 원래 줄과 함께 끝에 `outputs · commit=…` 요약이 찍힌다.

## 2. 읽기

Run 응답(REST `RunOut`, MCP `get_run`/`list_runs`)의 `outputs`에 `{key: value}`로 들어 있다. 가장 흔한 질문인 **"이 Job이 마지막으로 성공했을 때의 값"** 은 기존 조회로 바로 얻는다.

```bash
curl -s 'http://localhost:8000/api/runs?job_id=be-deploy&status=SUCCESS&limit=1' \
  | python3 -c 'import sys,json; r=json.load(sys.stdin); print(r[0]["outputs"].get("commit") if r else "")'
```

```
# MCP
list_runs(job_id="be-deploy", status="SUCCESS", limit=1)
```

웹 UI에서는 Step 로그 화면 상단(`→ commit=…`)과 Job 상세의 Runs 표 `Outputs` 열에 보인다.

## 3. 주의

- 출력값은 로그와 Run 기록에 그대로 남는다 — **비밀값을 출력하지 않는다.**
- 값은 step이 스스로 보고한 것이다. TaskFlow는 그것이 사실인지 검증하지 않는다.
