# 운영 가이드 — CLI 기반 측정 채널 / cron + worker 데몬 (Ubuntu)

이 문서는 구독 좌석 기반 CLI 3종(Claude Code CLI/Codex CLI/Gemini CLI)의 **인증 설정, 토큰
만료 대응, 배치 실행/예약 절차**를 다룬다. 각 CLI의 명령행 플래그/응답 스키마 등 조사 결과는
[docs/llm_clis.md](llm_clis.md)를 본다. 지표 계산 방식은 [docs/metrics.md](metrics.md)를 본다.
Ubuntu 서버 배포 절차는 [docs/deployment.md](deployment.md)를 본다.

## 0. 왜 API 키가 아니라 CLI 로그인인가

회사 사정으로 API 키를 발급받을 수 없어, 대신 **각 CLI를 로컬에 로그인시켜 두고 그 자격증명을
재사용**하는 방식으로 측정한다. 이는 곧 이 서비스의 배치가 실행되는 머신(운영 서버) 자체에 CLI
로그인이 되어 있어야 한다는 뜻이다 — API 키처럼 `.env`에 값을 넣는 것으로 끝나지 않는다.

**배치를 실행하는 프로세스는 `app/worker/daemon.py`(worker 데몬) 하나뿐이다** — 웹 앱(Flask/
Gunicorn)은 CLI를 직접 실행하지 않는다(migration_flask_postgres.md §2.3). 그래서 CLI 로그인도
worker 데몬을 실행하는 계정(systemd 유닛의 `User=`)에서 한 번만 해두면 된다.

## 1. Claude Code CLI 인증

```
claude setup-token
```

- 브라우저에서 Anthropic 계정으로 로그인 승인 후, **장기(long-lived) OAuth 토큰**을 발급한다.
- 발급된 토큰은 `CLAUDE_CODE_OAUTH_TOKEN` 환경변수로 설정하면 `claude` CLI가 헤드리스 환경에서도
  이 토큰을 사용한다(대화형 재로그인 불필요) — `geo-tracker-worker.service`의
  `EnvironmentFile=/opt/geo-tracker-flask/.env`에 이 값을 넣어둔다.
- 이 토큰은 Pro/Max/Team/Enterprise 등 **구독 플랜의 좌석**에 묶인다 — 팀 내 다른 사람이 같은
  좌석의 웹/앱 Claude를 동시에 많이 쓰면 이 서비스의 배치도 같은 rate limit을 공유해서 소진될 수
  있다. `CLAUDE_CODE_CONCURRENCY_LIMIT`(기본 1)을 보수적으로 유지하는 이유다.
- **Ubuntu 서버(GUI 없음)에서 이 브라우저 승인 플로우가 실제로 되는지는 미검증**이다
  (docs/risk_checklist.md §10). 안 되면 로컬 PC에서 `claude setup-token`을 실행해 토큰만 받아
  서버의 `.env`에 붙여넣는 방식으로 우회할 수 있다(토큰 자체는 브라우저 세션이 아니라 문자열
  값이므로 이 방식이 통할 가능성이 높다 — Phase 8에서 확인 필요).

### 토큰 만료 시

- `claude` 명령이 인증 오류로 실패하면(`cli_common.py`가 stderr에서 `not authenticated`류
  패턴을 감지해 `MissingAPIKeyError`로 분류 — 재시도하지 않고 즉시 실패 처리된다) `claude
  setup-token`을 다시 실행해 토큰을 재발급하고 `CLAUDE_CODE_OAUTH_TOKEN`을 갱신한 뒤
  `systemctl restart geo-tracker-worker`로 새 값을 반영한다.
- 배치 실행 전 상태 확인: `claude -p "ping" --output-format json --model sonnet`을 수동으로
  한 번 실행해보고 정상 JSON 응답이 오는지 확인한다(비용이 거의 들지 않는 짧은 호출).

## 2. Codex CLI 인증

```
codex login
```

- device-auth 흐름: 터미널에 코드가 표시되고, 다른 기기의 브라우저에서 그 코드를 입력해 로그인을
  승인한다. 승인되면 로컬에 자격증명이 저장된다(경로는 Codex CLI 버전에 따라 다를 수 있으므로
  `codex login --help`로 확인).
- 헤드리스 서버에서는 브라우저를 직접 열 수 없으므로, **최초 로그인은 사람이 개입해 코드를
  다른 기기에서 입력**해야 한다. 이후 재실행부터는 저장된 자격증명을 재사용해 완전히
  비대화형으로 동작한다.

### 토큰 만료 시

- 인증 오류 발생 시 `codex login`을 다시 실행한다(device-auth 흐름 재수행 필요 — 사람 개입
  필요).
- 사용량 한도 문구("You've hit your usage limit")는 인증 문제가 아니라 rate limit이다 —
  `CLIRateLimitError`로 분류되어 훨씬 긴 간격으로 재시도하며, 사람이 개입할 필요는 없다(다음
  주기까지 기다리면 풀린다).

## 3. Gemini CLI 인증

```
gemini
```

- 최초 실행 시 대화형으로 브라우저 OAuth 로그인을 유도한다. 승인하면 자격증명이 로컬에
  캐시된다.
- 이후 헤드리스 실행(`gemini -p "..." ...`)은 캐시된 자격증명을 자동으로 재사용한다 — 세 CLI
  중 재로그인 빈도가 가장 낮은 편이다.

### 토큰 만료 시

- 캐시된 자격증명이 만료되면 헤드리스 실행이 인증 오류로 실패한다 — 이 경우 `gemini`를
  대화형으로 한 번 실행해 재로그인해야 한다(사람 개입 필요).

## 4. 세 CLI의 인증 갱신 필요 빈도 비교

| CLI | 최초 설정 | 만료 시 갱신 방법 | 사람 개입 필요 여부 |
|---|---|---|---|
| Claude Code CLI | `claude setup-token` | 동일 명령 재실행 | 필요(브라우저 승인) |
| Codex CLI | `codex login`(device-auth) | 동일 명령 재실행 | 필요(다른 기기에서 코드 입력) |
| Gemini CLI | `gemini` 최초 대화형 실행 | `gemini` 재실행 | 필요(브라우저 승인) — 단, 만료 빈도가 가장 낮음 |

세 CLI 모두 **완전 무인 재인증은 불가능하다** — 토큰이 만료되면 누군가 한 번은 개입해야 한다.
그래서 배치가 실패하기 시작하면(특히 `MissingAPIKeyError`가 세 프로바이더 중 하나에서 계속
발생하면) 가장 먼저 확인할 것은 "이 CLI의 로그인이 만료됐는가"다.

## 5. 배치 실행 아키텍처 — worker 데몬 + cron

이 프로젝트는 예약 실행 방식이 하나뿐이다: **`geo-tracker-worker.service`(systemd, 상시 실행,
`Restart=on-failure`)가 유일한 CLI 실행 주체**이고, cron은 그 데몬에게 "이번 주 배치를
준비하라"는 신호(`POST /runs/trigger` 호출)만 보낸다 — cron 자신은 CLI를 전혀 실행하지 않는다
(migration_flask_postgres.md §2.3). 사전 조건:

1. **CLI 3종이 모두 worker 데몬 실행 계정에 설치되어 PATH에서 실행 가능해야 한다**
   (`geo-tracker-worker.service`의 `Environment=PATH=...` 참조, docs/llm_clis.md §7).
   `cli_common.require_cli_installed()`가 배치 시작 전 이를 확인하고, 없으면 즉시
   `MissingAPIKeyError`를 던진다.
2. **세 CLI 모두 위 1~3절의 로그인 절차를 미리 완료해두어야 한다.** 배치 자체는 로그인을 수행하지
   않는다 — 로그인은 사람이 미리 해두는 사전 조건이다.
3. **`CLI_WORKDIR`가 가리키는 디렉터리가 비어있어야 한다.** 이 디렉터리는 프로젝트와 무관한
   전용 폴더여야 하며(`cli_common.ensure_workdir_ready()`가 실행 전 확인), 이전 실행이 뭔가를
   남겼다면(예: Codex의 `-o` 임시 파일이 비정상 종료로 안 지워진 경우) 원인을 확인한 뒤 비워야
   한다.
4. **`MAX_CALLS_PER_BATCH` 설정값이 그 주의 예상 호출 수(활성 프롬프트 x 활성 프로바이더 x
   `REPEAT_COUNT`)보다 커야 한다.** 작으면 `POST /runs/trigger`가 `BatchTooLargeError`(HTTP
   400)를 반환하고 배치 자체가 시작되지 않는다 — 구독 좌석 rate limit을 실수로 소진하지 않기
   위한 의도된 동작이다.
5. `POST /runs/trigger`는 **즉시 응답한다**(execution_run을 PENDING으로 만들기만 함,
   docs/api.md §2.1) — 실제 실행은 이미 떠 있는 worker 데몬이 몇 초 안에 집어간다. 실행 후에는
   `GET /runs/{batch_id}/status`를 폴링해 `pending`/`running`이 0이 될 때까지 기다린 뒤
   `failed` 건수를 확인한다. `failed`가 있으면 원인이 인증 만료(위 1~4절)인지 일시적 오류인지
   구분하고, 인증 만료가 아니라면 `POST /runs/{batch_id}/resume`으로 재개한다(성공한 건은
   재실행되지 않는다).

## 6. cron 등록 절차

```
crontab -e   # geo-tracker-worker.service의 User=(예: geo-tracker) 계정으로, 또는 별도 관리용 계정으로
```

아래 한 줄을 추가한다(`.env`의 `WEEKLY_BATCH_CRON` 기본값 "매주 월요일 09:00"에 맞춘 예시 —
cron 문법 자체는 `.env`의 값을 그대로 못 쓰고 crontab 형식으로 다시 옮겨 적어야 한다는 점에
주의):

```
0 9 * * MON curl -sf -X POST http://localhost:8000/runs/trigger -H "X-Admin-Api-Key: <ADMIN_API_KEY 값>" >> /var/log/geo-tracker-trigger.log 2>&1
```

- **cron은 트리거 API만 호출한다 — CLI를 직접 실행하지 않는다.** 그래서 cron 특유의 빈약한
  `PATH` 환경변수 문제(cron이 만드는 셸은 로그인 셸이 아니라 `PATH`가 최소한으로만 설정됨)가
  애초에 발생하지 않는다 — 실제 CLI 실행 환경은 항상 `geo-tracker-worker.service`의 systemd
  `Environment=PATH=...`로 수렴하기 때문이다(참고 프로젝트가 Windows 작업 스케줄러에서 겪었던
  PATH 문제와 대비되는 부분).
- `curl -sf`의 `-f`는 HTTP 오류(4xx/5xx) 시 종료 코드를 0이 아니게 만든다 — cron이 실패를
  감지해 시스템 메일/로그로 알릴 수 있게 한다(`MAILTO=` crontab 설정 참고).
- 트리거는 즉시 반환하므로(§5-5) 이 cron 잡 자체는 몇 초 안에 끝난다 — 리버스 프록시/cron
  타임아웃을 걱정할 필요가 없다(이 설계를 애초에 선택한 이유, migration_flask_postgres.md §1
  사전 확인 #5).
- 실행 결과 확인은 cron 로그(`/var/log/geo-tracker-trigger.log`)가 아니라
  `GET /runs/{batch_id}/status`로 한다 — cron 로그에는 트리거가 접수됐다는 사실만 남고, 실제
  성공/실패는 worker 데몬이 나중에 채운다.
- 등록 후 처음에는 `MOCK_LLM=true`로 한 번 수동 트리거해서(`curl` 명령을 직접 실행) 정상 동작을
  확인하는 것을 권장한다(CLAUDE.md 규칙).

## 7. 호출량·좌석 사용 한도 모니터링

구독 좌석은 달러 단가가 아니라 "호출 횟수"로 rate limit이 걸린다(docs/llm_clis.md §6). 배치
전후로 아래 두 지점을 확인하는 습관이 곧 좌석 소진 사고를 막는 유일한 방법이다.

### 7.1 배치 시작 전 — 예상 호출 수 확인

`trigger_batch()`는 실행 전에 항상 `estimate_batch_calls()`로 예상 호출 수(활성 프롬프트 x
활성 프로바이더 x `REPEAT_COUNT`)를 계산하고, 이 값이 `MAX_CALLS_PER_BATCH`를 넘으면 배치를
아예 시작하지 않는다(`BatchTooLargeError`, `app/services/batch_runner.py`). 별도 조회 API는
없으므로, 트리거 전에 규모를 가늠하려면:

- 활성 프롬프트 수: `GET /prompts?is_active=true`(관리자 키 불필요, 목록 길이를 센다)
- 활성 프로바이더 수: `GET /llm-providers`(관리자 키 필요) 응답 중 `is_active: true`인 것만 센다
- `REPEAT_COUNT`: `GET /batch-config`(관리자 키 필요) 값 확인
- 위 세 값을 곱한 값이 `.env`의 `MAX_CALLS_PER_BATCH`보다 작은지 암산으로 확인한다. 애매하면
  그냥 트리거해본다 — 초과 시 배치가 시작되지 않고 `BatchTooLargeError` 메시지로 정확한 예상
  호출 수를 알려주므로, 실패해도 좌석을 소진하지 않는다.

### 7.2 배치 진행 중/종료 후 — 상태 폴링과 리포트 읽는 법

`POST /runs/trigger`(또는 `resume`) 응답과 `GET /runs/{batch_id}/status`는 같은 형식의
`BatchStatusResponse`를 반환하지만, **트리거/재개 직후에는 아직 실행 전이라 `pending`이 채워져
있고** `status` 엔드포인트를 폴링해야 최종 결과를 볼 수 있다(docs/api.md §2.1):

```json
{"batch_id": "2026-W29", "pending": 0, "running": 0, "success": 87, "failed": 3, "total_cost_usd": "0.369000"}
```

- `pending`/`running`이 오래도록 0이 되지 않으면 worker 데몬이 죽어있거나(가장 흔한 원인 —
  `systemctl status geo-tracker-worker`로 확인), CLI 로그인이 막혀 재시도를 반복하고 있는
  중일 수 있다.
- `failed > 0`이면 §1~4의 인증 만료가 첫 번째 의심 대상이다. 개별 실패 사유는 API 응답에
  포함되지 않으므로, `execution_run.error_message`를 직접 조회해야 한다(관리자 DB 접근, 또는
  §8의 검수 유틸리티). `MissingAPIKeyError`류 메시지가 보이면 재로그인(§1~3)이 필요하고,
  `CLIRateLimitError`류면 사람 개입 없이 다음 주기까지 기다리거나 나중에 `resume`한다.
- `total_cost_usd`는 CLI 좌석 채널에서는 대부분 0에 가깝다 — Claude Code CLI만 실비용을
  자기보고하고 Codex/Gemini CLI는 `cost_usd=None`이라 합계에서 빠진다(docs/llm_clis.md §6).
  "호출 수"가 진짜 모니터링 대상이지 이 필드가 아니다 — §7.1의 예상 호출 수와 실제
  `success + failed` 합을 비교하는 것이 더 의미 있는 점검이다.

## 8. 사람 검수 절차 (브랜드 매칭·감정 판정 표본 확인)

브랜드 언급 매칭(`app/services/brand_matching.py`)과 감정 분류(`app/services/sentiment.py`)는
규칙 기반이라 오탐/누락이 있을 수 있다.

> **참고 프로젝트(20260709)의 `app/services/review_dump.py` + `generate_review_sample.py`(원문+
> 하이라이트+감정+인용을 HTML 하나로 묶어주는 검수 유틸리티)는 이 Flask 재개발에서 아직
> 이식되지 않았다.** 지금은 관리자 API(`GET /prompts/{id}/detail?week=...`)의 `highlights`/
> `mentions`/`citations` 필드를 직접 조회해 같은 정보를 얻을 수 있다 — 표본 수가 많아지면 위
> 유틸리티를 포팅하는 것을 검토한다(docs/backlog.md 후보로 추가 가능).

**주기: 실측(MOCK_LLM=false) 배치가 도입된 이후로는 매주 배치 직후 최소 1회.** 특히 새 브랜드/
별칭을 추가했거나 프롬프트를 신규 버전으로 교체한 직후에는 반드시 확인한다. 확인할 것:

- 하이라이트된 텍스트가 실제로 그 브랜드를 가리키는지(과매칭 — 예: 브랜드명이 다른 고유명사의
  부분 문자열인 경우)
- 하이라이트되어야 할 언급이 빠지지 않았는지(누락 — 별칭 표기가 `brand_alias`에 없는 경우)
- 감정 판정(긍정/중립/부정)이 문맥상 타당한지 — `sentiment_evidence`에 표시된 근거 문장을
  기준으로 판단한다
- 인용 URL이 실제로 그 브랜드의 도메인과 매칭됐는지(`brand_domain` 등록 누락 여부)

이 검수는 배치 파이프라인을 바꾸지 않는다 — 문제를 발견하면 `brand_alias`/`brand_domain`을
관리 API로 보정하거나(`docs/api.md` §2), 매칭/감정 로직 자체의 결함이면 별도 이슈로 기록한다.

## 9. 월 1회 수동 스팟 체크 (소비자 챗봇과의 방향성 비교)

**이 절차는 자동화하지 않는다 — 사람이 매달 한 번, 수동으로만 수행한다.** CLI 측정치가
"소비자가 실제로 AI에게 물었을 때"의 근사치(proxy)에 불과하다는 한계(docs/metrics.md §7.1)를
실제로 얼마나 벗어나 있는지 주기적으로 감을 잡기 위한 절차다 — 자동화하면 이 서비스가 원래
피하려던 "API/자동 호출로 소비자 제품에 접근" 문제를 다시 만들게 되므로 의도적으로 사람이
직접 브라우저에서 입력한다.

### 절차

1. `GET /prompts?priority=High&is_active=true`로 High 우선순위 활성 프롬프트를 확인하고, 그 중
   **10~20개를 무작위 또는 대표성 있게 선정**한다.
2. 각 프롬프트 텍스트를 **그대로 복사**해 ChatGPT 웹(chat.openai.com)과 Gemini 웹(gemini.google.com)
   에 사람이 직접 입력한다(로그인된 일반 소비자 계정 사용 — API 아님).
3. 아래 템플릿에 결과를 기록한다.
4. 이번 CLI 배치의 같은 프롬프트·같은 주차 결과(`GET /prompts/{id}/detail?week=...`)와 나란히
   놓고 비교한다 — **정확한 SOV 수치 일치를 기대하지 않는다.** 확인할 것은 방향성이다: 우리
   브랜드가 언급되는지 여부, 대략 몇 번째로 언급되는지(먼저/나중), 톤이 긍정/중립/부정 중
   무엇인지.

### 기록 템플릿

```markdown
## 스팟 체크 — 2026년 O월

| 프롬프트 ID | 프롬프트(요약) | CLI 배치: 우리 브랜드 언급? | CLI: 대략 순서 | ChatGPT 웹: 언급? | ChatGPT: 대략 순서 | Gemini 웹: 언급? | Gemini: 대략 순서 | 방향성 일치? | 비고 |
|---|---|---|---|---|---|---|---|---|---|
| 12 | 국내 포워딩 플랫폼 추천 | Y | 1번째 | Y | 2번째 | Y | 1번째 | 대체로 일치 | ChatGPT가 경쟁사를 먼저 언급 |
| 27 | B/L과 화물운송장 차이 | N | - | N | - | Y | 3번째 | 부분 불일치 | Gemini만 우리 브랜드 언급 |

**총평(1~2문단)**: 이번 달 CLI 측정치와 소비자 챗봇 간 방향성이 대체로 일치했는지, 특정
프롬프트 유형(예: 정의형 질문 vs 추천형 질문)에서 괴리가 컸는지 등을 자유 서술로 남긴다.
```

이 기록은 별도 문서(예: `docs/spot_checks/2026-07.md`)로 매달 누적하는 것을 권장한다 — 이
저장소에는 템플릿만 두고, 실제 기록 파일은 필요 시점에 새로 만든다.

## 10. 관련 문서

- Ubuntu 서버 배포 절차: [docs/deployment.md](deployment.md)
- 지표 정의(SSOT): [docs/metrics.md](metrics.md)
- CLI별 명령행/응답 스키마 조사: [docs/llm_clis.md](llm_clis.md)
- 운영 리스크 체크리스트: [docs/risk_checklist.md](risk_checklist.md)

## 11. 변경 이력

| 날짜 | 변경 내용 |
|---|---|
| 2026-07-10 | 참고 프로젝트(20260709) STEP 6: CLI 기반 측정 전환에 따라 최초 작성 |
| 2026-07-10 | 참고 프로젝트 STEP 7: §5 재구성(방식 A/B 공통 사전조건), §6 Windows 작업 스케줄러 등록 절차 추가 |
| 2026-07-13 | 참고 프로젝트 STEP 7: §7 호출량 모니터링, §8 사람 검수 절차, §9 월 1회 수동 스팟체크 추가 |
| 2026-07-15 | Flask+PostgreSQL+Ubuntu 재개발: §5/§6을 worker 데몬+cron 구조로 전면 교체(Windows 작업 스케줄러 절차 제거), §7.2를 트리거 즉시 응답 계약에 맞춰 갱신, §8에 review_dump 유틸 미이식 사실 명시 |
