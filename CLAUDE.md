# CLAUDE.md

이 파일은 이 저장소에서 작업하는 모든 세션(사람/에이전트)이 따라야 하는 기준 문서다.
스택이나 규칙을 바꾸려면 이 파일을 먼저 갱신하고 작업을 시작한다.

## 프로젝트 한 줄 요약

**GEO Weekly Tracker**는 B2B 물류 브랜드(삼성SDS, 첼로스퀘어 등)가 AI의 답변에서 얼마나
언급·인용되는지를 주간 단위로 **실측**하는 서비스다. North Star 지표는 **AI SOV(Share of
Voice)**이며, 경쟁사 대비 상대적 언급 비중으로 정의한다(정확한 계산식은
[docs/metrics.md](docs/metrics.md) 참조).

**이 프로젝트는 참고 프로젝트 `C:\자료\작업중\20260709`(FastAPI+SQLite+Windows)를 Flask+
PostgreSQL+Ubuntu로 재개발한 것이다.** 재개발 사유: FastAPI+uvicorn 배포는 담당자가 ASGI 서버
설정 절차를 거쳐야 하는데, Flask+Gunicorn은 사내 서버가 이미 익숙한 표준 WSGI 배포 방식이라
담당자의 작업 공수를 최소화할 수 있다고 판단했다. 재개발 설계 근거와 단계별 작업 지시는
[docs/migration_flask_postgres.md](docs/migration_flask_postgres.md)(참고 프로젝트에 보존됨)를
참고한다 — 특히 §2.3(웹 앱과 worker 데몬을 분리해야 하는 이유, Opus 4.8 리뷰로 발견된 치명적
설계 결함과 그 수정)는 이 아키텍처를 이해하는 데 필수적이다.

측정 채널은 소비자용 채팅 제품이 아니라 **구독 좌석 기반 코딩 에이전트 CLI 3종(Claude Code
CLI/Codex CLI/Gemini CLI)**이다(Perplexity는 전용 CLI가 없어 측정 대상에서 제외). 이 CLI들은
코딩 에이전트이므로, 이 서비스가 재는 지표는 소비자 대화형 AI에서의 노출도를 완전히 대체하지
못하는 **proxy(대리 지표)**다 — 상세 근거는 [docs/llm_clis.md](docs/llm_clis.md), 한계는
[docs/metrics.md](docs/metrics.md) §7 참조.

## 확정 기술 스택

- **백엔드**: Python 3.11+ / Flask 3.x (WSGI, 동기) + Gunicorn
- **DB**: PostgreSQL + SQLAlchemy 2.x(동기, `psycopg` 드라이버) + Alembic 마이그레이션. 엔진
  생성은 항상 `app/db/engine.py`의 `create_configured_engine()`을 거친다(직접
  `create_engine()`을 쓰지 않는다). Docker를 쓸 수 있는 환경이면
  `deploy/optional/docker-compose.yml`로 Postgres 컨테이너 전환 가능(코드 변경 없음).
- **배치 아키텍처 (가장 중요한 설계 결정 — §핵심 도메인 규칙 4 참조)**: 웹 앱(Flask/Gunicorn)과
  **완전히 분리된, 정확히 1개 인스턴스만 도는** 별도 프로세스 `app/worker/daemon.py`
  (`WeeklyBatchWorker`)가 CLI 실행을 전담한다. 웹 앱은 `app/services/batch_runner.py`의
  `trigger_batch()`/`resume_batch()`로 execution_run을 PENDING으로 만들기만 하고 즉시
  반환한다 — CLI 서브프로세스를 직접 실행하지 않는다. 프론트엔드는
  `GET /runs/{batch_id}/status`를 폴링해 진행 상황을 확인한다(§2.5). systemd 유닛 2개
  (`deploy/systemd/geo-tracker-web.service`, `geo-tracker-worker.service`)로 운영한다.
- **CLI 실행 엔진**: `subprocess.Popen(start_new_session=True, ...)` 기반 동기 실행
  (`app/llm_clients/cli_common.py`). 타임아웃 시 `os.killpg(os.getpgid(pid), SIGKILL)`로
  프로세스 그룹 전체를 죽인다(POSIX 전용 — Ubuntu 운영 환경 기준 필수 구현). 프로바이더별
  `ThreadPoolExecutor`(worker 데몬 프로세스 안에 정확히 하나씩만 존재)로 동시성을 제어한다.
- **스케줄링**: cron이 `POST /runs/trigger`만 호출한다(CLI를 직접 실행하지 않음) — 실제 실행은
  항상 이미 떠 있는 worker 데몬이 집어간다(docs/operations.md §6).
- **프론트엔드**: 빌드 도구 없는 정적 파일(`frontend/`) + 브라우저 네이티브 ES 모듈 + `fetch`.
  참고 프로젝트의 `frontend/`를 그대로 재사용했다 — 배치 트리거가 "즉시 응답 + 상태 폴링"
  방식으로 바뀐 것에 맞춰 `js/api.js`(`pollBatchUntilDone()` 추가)와 `js/main.js`/
  `js/dashboard.js`(트리거/재개 핸들러)만 수정했다.
- **LLM 클라이언트**: `backend/app/llm_clients/`의 어댑터 레이어. 활성 구현체는 CLI 3종뿐이다
  (`claude_code_cli_adapter.py`/`codex_cli_adapter.py`/`gemini_cli_adapter.py`, 모두
  `cli_common.py`의 동기 `run_cli()` 기반). 참고 프로젝트의 레거시 SDK 4개 어댑터(OpenAI/
  Gemini/Anthropic/Perplexity 공식 SDK)는 **이 재개발에서 이식하지 않았다** — 회사 사정으로
  그 API 키 자체가 없어 실제로 쓰이지 않는 경로이기 때문이다. API 키를 다시 받으면
  [docs/backlog.md](docs/backlog.md)의 절차대로 참고 프로젝트에서 새로 포팅한다.
- **감정 분류**: `app/services/sentiment.py`의 `KeywordRuleSentimentClassifier`(규칙 기반)만
  있다 — OpenAI 키가 없어 `LLMSentimentClassifier`(소형 LLM 기반)는 이식하지 않았다
  (docs/metrics.md §7.3.1).
- **린트/포맷**: `ruff` 단일 도구. **테스트**: `pytest`(동기 — `pytest-asyncio` 불필요, 이
  프로젝트에 async 코드가 없다).

## 폴더 구조

```
geo-tracker-flask/
├── backend/
│   ├── app/
│   │   ├── api/          # Flask Blueprint 라우트
│   │   ├── core/         # 설정(config), 인증(ADMIN_API_KEY 데코레이터) 등 횡단 관심사
│   │   ├── db/           # DB 세션/엔진 (session.py — 테스트용 오버라이드 메커니즘 포함)
│   │   ├── models/       # SQLAlchemy ORM 모델
│   │   ├── schemas/      # Pydantic 요청/응답 스키마
│   │   ├── services/     # 도메인 로직. 트리거 계층(Flask/worker)에 종속되지 않는 순수 로직
│   │   ├── llm_clients/  # LLM 프로바이더 어댑터 (CLI 3종만 — legacy SDK 없음)
│   │   └── worker/       # daemon.py — 유일한 CLI 실행 프로세스
│   ├── alembic/          # DB 마이그레이션
│   ├── gunicorn.conf.py  # 웹 앱 전용 Gunicorn 설정
│   └── tests/            # pytest (동기)
├── frontend/    # 참고 프로젝트 frontend/ 재사용 (트리거 폴링 로직만 수정)
├── docs/        # 도메인 문서. metrics.md는 지표 정의의 단일 진실 원천(SSOT)
│   ├── metrics.md              # 지표 정의 SSOT
│   ├── erd.md                  # 데이터 모델 ERD(mermaid)
│   ├── api.md                  # API 엔드포인트 요약표 + §2.1 트리거 즉시 응답 계약
│   ├── llm_clis.md             # CLI 3종 조사 + §7 Ubuntu 실행 방식
│   ├── operations.md           # 인증/cron 등록/호출량 모니터링/사람 검수/월 1회 스팟체크
│   ├── deployment.md           # Ubuntu 배포 절차 (systemd 유닛, cron, PostgreSQL 백업/복원)
│   ├── risk_checklist.md       # 운영 리스크 점검표
│   └── backlog.md              # 스코프 밖 백로그
├── deploy/
│   ├── systemd/                 # geo-tracker-web.service, geo-tracker-worker.service
│   └── optional/docker-compose.yml  # Docker 사용 가능 환경에서 Postgres 컨테이너 전환용
├── scripts/     # setup.sh(최초 1회), run.sh(로컬 개발용 — worker 데몬은 별도 실행)
├── data/        # keywords.json(프롬프트 시드) 등
├── CLAUDE.md    # 이 파일
└── .env.example
```

## 코딩 컨벤션

- **타입 힌트 필수.** 모든 함수/메서드의 인자와 반환값에 타입을 명시한다. `Any`는 정말 불가피할
  때만 사용하고 이유를 주석으로 남긴다.
- **포맷/린트**: `ruff format` + `ruff check`를 커밋 전에 통과해야 한다.
- **테스트**: `pytest` 사용(동기). FastAPI 엔드포인트 테스트는 `httpx.AsyncClient`를 썼던 참고
  프로젝트와 달리, 이 프로젝트는 Flask `app.test_client()`로 실제 라우팅을 통과시켜 검증한다.
  관리자 API 테스트는 `tests/conftest.py`의 `client`(단일 롤백 세션, `db_session` 기반)/
  `client_committing`(요청마다 새 세션, `session_factory` 기반 — worker 데몬처럼 실제 커밋이
  필요한 통합 테스트용) 픽스처를 쓴다.
- **도메인 로직과 트리거 계층 분리**: 배치/SOV 계산 등의 로직은 `services/`에 Flask 라우트나
  worker 데몬에 의존하지 않는 형태로 작성한다.
- 불필요한 추상화, 사용하지 않는 기능을 위한 방어 코드, 과도한 주석을 추가하지 않는다(WHY가
  비자명한 경우에만 주석 작성).
- **DB 세션 테스트 오버라이드 규칙**: Flask에는 FastAPI의 `app.dependency_overrides`가 없다 —
  대신 `app/db/session.py`의 `set_session_override()`(고정 세션 재사용, 롤백 격리용)와
  `set_session_factory_override()`(요청마다 새 세션 생성 + `teardown_appcontext`에서 반드시
  `close()` — 이 close()를 빠뜨리면 커넥션이 유휴 트랜잭션 상태로 풀에 남아 이후 `TRUNCATE` 등이
  무한 대기하게 된다, 2026-07-15 실측 확인)를 쓴다. 새 테스트 픽스처를 추가할 때 이 두 함수
  중 어느 것을 오버라이드로 쓸지, 그리고 테스트 종료 시 반드시 `None`으로 해제하는지 확인한다.

## 핵심 도메인 규칙

1. **브랜드는 고유 ID로만 참조한다. 배열 순서 인덱스로 브랜드를 매핑하지 않는다.**
   - 백엔드/DB 모델에서는 브랜드마다 안정적인 고유 ID(정수 PK)를 부여하고, 이 ID로만 참조한다.
     순서가 바뀌거나 브랜드가 추가/삭제돼도 기존 데이터의 브랜드 식별이 깨지면 안 된다.

2. **프롬프트 텍스트는 불변이다. 수정 시 새 버전을 생성한다.**
   - 이미 실행 이력이 쌓인 프롬프트의 텍스트를 그 자리에서 고쳐 쓰면 과거 측정값의 의미가
     달라진다. 프롬프트 문구를 바꿔야 하면 새 버전(새 레코드, `supersedes_id`로 이전 버전과
     연결)을 만들고, 과거 실행 결과는 그 시점의 버전에 귀속된 채로 남긴다. 텍스트 수정 API
     자체가 존재하지 않는다(`create_prompt()` + `deactivate_prompt()`만 있음).

3. **`MOCK_LLM=true`가 개발 기본값이다. 실제 LLM CLI 호출은 명시적 승인 없이 하지 않는다.**
   - 로컬 개발/테스트/CI에서는 `.env`의 `MOCK_LLM=true`를 유지하고 `app/llm_clients/mock.py`의
     고정 응답을 사용한다(실제 서브프로세스를 띄우지 않는다). 실제 CLI를 호출하는 코드 경로
     (구독 좌석 rate limit 소모)는 사용자가 명시적으로 `MOCK_LLM=false`를 요청하거나 실측을
     승인한 경우에만 실행한다.

4. **배치 실행은 웹 앱 프로세스에서 절대 하지 않는다 (가장 중요한 아키텍처 규칙).**
   - `app/api/runs.py`는 `app/llm_clients/`를 **import하지 않는다** — 이 조건을 깨는 변경은
     §2.3의 분리 원칙을 위반하는 것이다. `trigger_batch()`/`resume_batch()`는 execution_run을
     PENDING으로 만들거나 되돌리기만 하고 즉시 반환한다.
   - `app/worker/daemon.py`(`WeeklyBatchWorker`)가 유일한 CLI 실행 주체이며, **정확히 1개
     인스턴스만 떠야 한다**(systemd가 보장 — `geo-tracker-worker.service`를 실수로 두 번
     enable하거나 터미널에서 추가로 수동 실행하지 않는다, docs/risk_checklist.md §8).
   - CLI 실행: `subprocess.Popen(start_new_session=True, ...)`으로 새 세션을 만들고, 타임아웃 시
     `os.killpg(os.getpgid(pid), SIGKILL)`로 프로세스 그룹 전체를 죽인다(단순 `process.kill()`은
     자식 프로세스를 정리하지 못해 좀비를 남긴다 — 필수 구현, 선택 아님).
   - 세 CLI 모두 `CLI_WORKDIR`(프로젝트와 무관한 전용 빈 디렉터리)를 cwd로 실행한다
     (`cli_common.ensure_workdir_ready()`가 실행 전 비어있음을 확인). **Claude Code CLI는
     `--bare`를 쓰지 않는다**(`CLAUDE_CODE_OAUTH_TOKEN` 인증을 인식 못 하는 버전 제약 실측
     확인). **Codex CLI는 `--skip-git-repo-check`를 쓰고 `--search`는 쓰지 않는다**(각각
     "git 저장소 아니면 거부"/ "v0.144.1부터 플래그 자체가 제거됨" 실측 확인) —
     [docs/llm_clis.md](docs/llm_clis.md) §1~2 참조.
   - 배치 시작 전 예상 호출 수(활성 프롬프트 x 활성 CLI x `REPEAT_COUNT`)가
     `MAX_CALLS_PER_BATCH`를 넘으면 배치를 거부한다(`BatchTooLargeError`).
   - 프로바이더별 동시 실행 상한(`*_CONCURRENCY_LIMIT`, 기본 1~2)을 보수적으로 유지한다 — 이
     상한은 worker 데몬 프로세스 하나 안에서만 의미를 가지므로(여러 프로세스에 걸쳐 나뉘지
     않음), 실제 상한이 곧 이 값 그대로다.

5. **DB는 PostgreSQL 전용이다. SQLite 폴백은 없다.**
   - 참고 프로젝트(SQLite)와 달리 다이얼렉트 분기 로직 자체가 없다 — `weekly_snapshot`의 부분
     유니크 인덱스도 `postgresql_where=`만 지정한다(`sqlite_where=`는 불필요해 제거함,
     docs/erd.md §2 참조).
   - `ALTER TABLE`이 필요한 마이그레이션도 SQLite의 batch 모드 우회가 필요 없다 — 표준 Alembic
     `op.alter_column()` 등을 그대로 쓴다.
   - DB 엔진은 항상 `app/db/engine.py`의 `create_configured_engine()`으로 만든다.
   - 다른 서버로 이전은 `pg_dump`/`psql` 기반이다(폴더 복사로 안 됨) — [docs/deployment.md](docs/deployment.md)
     §6 참조.

## 지표 정의 (Single Source of Truth)

**모든 지표(AI SOV, AI Visibility, Mentions, Citation 등)의 정의와 계산식은
[docs/metrics.md](docs/metrics.md)를 단일 진실 원천으로 한다.** 코드에서 지표를 계산하는 로직을
작성하거나 수정할 때는 반드시 `docs/metrics.md`를 먼저 확인하고, 문서와 다르게 구현해야 할 이유가
있으면 코드보다 문서를 먼저 갱신한다. 데이터 모델 자체의 구조(테이블/관계/제약)는
[docs/erd.md](docs/erd.md)를, API 엔드포인트 목록은 [docs/api.md](docs/api.md)를 참조한다.

## 현재 진행 상태

Flask+PostgreSQL 재개발 Phase 0~6 완료, Phase 7(테스트/배포 구성/문서) 진행 중:

- **Phase 0~1**: Flask 프로젝트 골격 + PostgreSQL 마이그레이션(Alembic autogenerate로 검증) 완료.
- **Phase 2**: 도메인 로직(aggregation/brand_matching/citation_extraction/week_utils/sentiment/
  response_parser) 동기 이식 + 단위 테스트 58개 통과.
- **Phase 3**: CLI 실행 엔진 동기 재작성(`subprocess.Popen`+프로세스 그룹 kill) — 26개 단위
  테스트 통과(mock 기반). **실제 Ubuntu 환경에서의 `.cmd` 우회 불필요 확인/프로세스 그룹 종료
  실측 검증은 아직 못함**(이 개발이 이루어진 PC에 WSL/Docker가 없어 Linux 환경 자체를 구성하지
  못했다 — Phase 8에서 실제 배포 서버 기준으로 반드시 재확인해야 하는 항목으로 남아있다).
- **Phase 4**: 배치 오케스트레이션 재설계(트리거/worker 데몬 분리) — 실제 서브프로세스로 띄운
  worker 데몬 통합 테스트, 동시성 상한 실측 테스트 포함 95개 통과.
- **Phase 5**: Flask Blueprint API 계층 — 관리자 CRUD 포함 160개 테스트 통과.
- **Phase 6**: 프론트엔드 폴링 전환 — 브라우저에서 실제 트리거→폴링→완료 흐름 확인 완료.
- **Phase 7**: systemd 유닛 2개, CLAUDE.md/README/docs 전체 작성, 웹 앱 강제 재시작에도 worker
  데몬 배치가 안 끊기는 것을 실측 확인.
- **Phase 8 (부분 완료, 2026-07-16, 이 Windows PC에서 소규모 실측)**: `MOCK_LLM=false`로 실제
  프롬프트 2개 x Claude Code CLI/Codex CLI를 이 새 아키텍처(트리거→worker 데몬→실 CLI
  서브프로세스→파싱→집계)로 실행. 결과:
  - **Claude Code CLI: 2/2 성공.** 실제 응답 텍스트, 실비용(`$0.057641`/`$0.103988`) 정상 기록,
    citation 정규식 폴백이 실제 응답에서 URL 7개를 정확히 추출(등록 안 된 도메인은
    `matched_brand_id=NULL`로 정확히 처리) — 파이프라인 전체가 실제 응답으로 end-to-end 동작함을
    확인. 두 프롬프트 모두 추적 브랜드가 실제로 언급되지 않아 `mention` 행은 0건(정상 — 실제
    LLM 응답이 그 브랜드를 언급하지 않은 것뿐, 파싱 실패가 아님).
  - **Codex CLI: 2/2 실패, 원인 2가지 확인.** ① `FileNotFoundError: [WinError 2]` — npm으로 설치된
    `codex.cmd`(Windows 셸 스크립트)를 `subprocess.Popen(["codex", ...])`이 직접 실행하지 못함.
    이 재개발은 Ubuntu 전용이라 Windows `.cmd` 우회 코드(`_adapt_for_windows()`)를 의도적으로
    이식하지 않았으므로(docs/llm_clis.md §7.1) **예상된 실패이지 버그가 아니다** — Ubuntu
    서버(npm이 실행 가능한 셸 스크립트를 만듦)에서는 재현되지 않아야 하며, 이는 여전히 실측
    확인이 필요하다. ② 이 계정의 Codex 사용량 한도가 이미 소진되어 있어(2026-08-12 KST
    13:35 리셋 예정 — CLI 자체 에러 메시지 기준) 위 ①과 무관하게 어차피 이번 계정으로는
    당장 실호출이 안 됐을 것 — docs/risk_checklist.md §5에 반영.
  - **Gemini CLI: 미실행.** 헤드리스 실행 시 브라우저 인증 재확인 프롬프트(`Opening
    authentication page... [Y/n]`)가 떠서 캐시된 자격증명이 없거나 만료된 상태로 확인됨 —
    사람이 대화형으로 `gemini` 재로그인을 완료해야 다음 파일럿에서 시도 가능(docs/operations.md
    §3).
  - **결론**: 새 Flask+PostgreSQL+worker 데몬 아키텍처 자체는 실제 CLI 응답으로 정상 동작함을
    확인(가장 중요한 목표 달성). Windows `.cmd` 비호환/실제 Ubuntu 프로세스 그룹 kill 검증은
    여전히 미완료로 남아 실제 Ubuntu 배포 서버에서 재확인이 필요하다.
- **다음 단계**: 실제 Ubuntu 서버 배포 후 Phase 8 나머지 항목(Codex/Gemini CLI 정상 실행 확인,
  cron 실제 트리거, systemd 재시작 중 배치 무중단 확인) 재검증.
