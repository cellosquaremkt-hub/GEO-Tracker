# GEO Weekly Tracker (Flask + PostgreSQL)

B2B 물류 브랜드의 AI 언급/인용을 주간 단위로 실측하는 서비스. 자세한 설계/규칙은
[CLAUDE.md](CLAUDE.md)를 참조한다.

## 로컬 개발 환경 실행

### 사전 준비

- Python 3.11+
- PostgreSQL (로컬에 `geo_weekly_tracker`/`geo_weekly_tracker_test` 데이터베이스와 `geo` 롤 준비)
- Node.js 18+ (Codex/Gemini CLI 실사용 시에만 필요 — `MOCK_LLM=true` 개발에는 불필요)

### 최초 1회 설정

```bash
cp .env.example .env   # 값을 실제 로컬 PostgreSQL 접속 정보로 채운다
cd backend
python3 -m venv .venv
.venv/bin/pip install -e ".[dev]"
.venv/bin/python -m alembic upgrade head
.venv/bin/python -m app.db.seed
```

### 서버 실행 (개발 — 별도 터미널 2~3개)

```bash
# 1. 웹 API (backend/)
.venv/bin/flask --app app.main run --port 8000

# 2. worker 데몬 (backend/) — 실측 배치가 필요할 때만. MOCK_LLM=true여도 배치 파이프라인
#    검증을 위해 띄워두는 것을 권장한다.
.venv/bin/python -m app.worker.daemon

# 3. 프론트엔드 정적 서버 (frontend/)
python3 -m http.server 5500
```

브라우저에서 `http://localhost:5500` 접속. Settings 화면에서 `.env`의 `ADMIN_API_KEY` 값을
입력해야 관리자 기능(주간 실행, 브랜드/프롬프트 관리 등)을 쓸 수 있다.

## 테스트

```bash
cd backend
.venv/bin/python -m pytest tests/
.venv/bin/python -m ruff check app/ tests/
.venv/bin/python -m ruff format --check app/ tests/
```

테스트는 `TEST_DATABASE_URL`(별도 PostgreSQL DB)을 쓴다 — 개발 DB를 오염시키지 않는다.

## 배포

Ubuntu 서버 배포 절차는 [docs/deployment.md](docs/deployment.md) 참조 (systemd 유닛 2개 +
cron). 이 서비스는 웹 앱과 배치 실행(worker 데몬)이 완전히 분리된 아키텍처다 — 자세한 이유는
CLAUDE.md와 `docs/deployment.md` §0을 참조.

## 문서 목차

- [CLAUDE.md](CLAUDE.md) — 스택/규칙 기준 문서
- [docs/metrics.md](docs/metrics.md) — 지표 정의 SSOT
- [docs/erd.md](docs/erd.md) — 데이터 모델
- [docs/api.md](docs/api.md) — API 엔드포인트 요약
- [docs/llm_clis.md](docs/llm_clis.md) — CLI 3종 조사
- [docs/operations.md](docs/operations.md) — 운영 절차(인증/cron/모니터링/검수)
- [docs/deployment.md](docs/deployment.md) — Ubuntu 배포
- [docs/risk_checklist.md](docs/risk_checklist.md) — 운영 리스크 체크리스트
- [docs/backlog.md](docs/backlog.md) — 스코프 밖 백로그
