# 배포 절차 (Ubuntu)

이 문서는 GEO Weekly Tracker(Flask + PostgreSQL + Gunicorn + worker 데몬)를 Ubuntu 서버에
배포하는 절차를 다룬다. 참고 프로젝트(20260709, Windows+SQLite)의 `docs/deployment.md`(폴더
복사 기반 이전)와는 전제 자체가 다르므로 완전히 새로 작성됐다.

## 0. 아키텍처 요약

이 서비스는 서버에서 **항상 2개의 독립된 프로세스**가 떠 있어야 한다(migration_flask_
postgres.md §2.3):

1. **웹 앱** (`geo-tracker-web.service`) — Gunicorn이 Flask 앱을 실행. HTTP 요청만 처리하고
   CLI를 절대 실행하지 않는다. 재시작/배포해도 배치 실행에 영향이 없다.
2. **worker 데몬** (`geo-tracker-worker.service`) — `python -m app.worker.daemon`. **정확히
   1개 인스턴스만 떠 있어야 한다.** PENDING execution_run을 폴링해서 CLI(Claude Code/Codex/
   Gemini)를 실제로 실행하는 유일한 프로세스다.

cron은 이 둘과 별개로, 매주 한 번 트리거 API만 호출한다(§4 참조) — CLI를 직접 실행하지 않는다.

## 1. 사전 준비

### 1.1 시스템 패키지

```bash
sudo apt update
sudo apt install -y python3.11 python3.11-venv postgresql postgresql-contrib nodejs npm
```

- Python 3.11+ 확인: `python3.11 --version`
- **Node.js는 시스템 전역 설치(위 apt 방식 또는 NodeSource)를 권장한다** — nvm은 경로에 Node
  버전 문자열이 포함되어(`~/.nvm/versions/node/<버전>/bin`) Node를 업그레이드할 때마다
  `geo-tracker-worker.service`의 `Environment=PATH=...`를 갱신해야 하는 부담이 생긴다
  (docs/risk_checklist.md §9). Codex CLI는 Node.js 22+, Gemini CLI는 Node.js 18+가 필요하다 —
  `node --version`으로 사전 확인.

### 1.2 전용 시스템 사용자

```bash
sudo useradd --system --create-home --shell /bin/bash geo-tracker
sudo -u geo-tracker -i
```

이후 CLI 설치/로그인은 모두 이 계정으로 한다(`geo-tracker-worker.service`의 `User=`와 일치해야
로그인 자격증명을 데몬이 찾을 수 있다).

### 1.3 CLI 3종 설치 (geo-tracker 계정으로)

```bash
curl -fsSL https://claude.ai/install.sh | bash        # Claude Code CLI
npm install -g @openai/codex                            # Codex CLI (Node.js 22+)
npm install -g @google/gemini-cli                        # Gemini CLI (Node.js 18+)
```

설치 경로 확인: `which claude codex gemini` — 이 경로들을 `geo-tracker-worker.service`의
`Environment=PATH=...`에 반영한다(기본 템플릿은 `~/.local/bin`과 `/usr/local/bin`을 이미
포함하므로, apt/NodeSource 표준 경로라면 수정 없이 맞을 가능성이 높다).

### 1.4 CLI 로그인 (geo-tracker 계정으로, 최초 1회)

`docs/operations.md` §1~3 절차대로 `claude setup-token` / `codex login` / `gemini` 최초
실행을 수행한다. **Ubuntu 서버(GUI 없음)에서 브라우저 승인 플로우가 실제로 되는지는 Phase 8
전까지 미검증**이다(docs/risk_checklist.md §10) — 안 되면 로컬 PC에서 로그인 후 자격증명/토큰을
서버로 옮기는 방식을 검토한다.

### 1.5 PostgreSQL 준비

```bash
sudo -u postgres psql -c "CREATE ROLE geo WITH LOGIN PASSWORD '<강력한 비밀번호>';"
sudo -u postgres psql -c "CREATE DATABASE geo_weekly_tracker OWNER geo;"
sudo -u postgres psql -c "CREATE DATABASE geo_weekly_tracker_test OWNER geo;"
```

Docker를 쓸 수 있는 환경이라면 `deploy/optional/docker-compose.yml`로 대체 가능하다(코드 변경
없이 `DATABASE_URL`만 바꾸면 된다 — docs/backlog.md 참조).

## 2. 코드 배포

```bash
sudo mkdir -p /opt/geo-tracker-flask
sudo chown geo-tracker:geo-tracker /opt/geo-tracker-flask
sudo -u geo-tracker git clone <repo-url> /opt/geo-tracker-flask   # 또는 rsync/scp로 복사
cd /opt/geo-tracker-flask/backend
sudo -u geo-tracker python3.11 -m venv .venv
sudo -u geo-tracker .venv/bin/pip install -e .
```

`.env` 준비:

```bash
cd /opt/geo-tracker-flask
sudo -u geo-tracker cp .env.example .env
sudo -u geo-tracker nano .env   # DATABASE_URL, ADMIN_API_KEY, CLAUDE_CODE_OAUTH_TOKEN 등 실제 값 채우기
```

DB 마이그레이션 + 시딩:

```bash
cd /opt/geo-tracker-flask/backend
sudo -u geo-tracker .venv/bin/python -m alembic upgrade head
sudo -u geo-tracker .venv/bin/python -m app.db.seed
```

## 3. systemd 유닛 등록

유닛 파일은 `deploy/systemd/`에 이미 준비되어 있다 — `User=`/`WorkingDirectory=`/
`EnvironmentFile=`의 경로가 실제 배포 경로(`/opt/geo-tracker-flask`)와 일치하는지 확인한 뒤:

```bash
sudo cp deploy/systemd/geo-tracker-web.service /etc/systemd/system/
sudo cp deploy/systemd/geo-tracker-worker.service /etc/systemd/system/
sudo systemctl daemon-reload
sudo systemctl enable --now geo-tracker-web
sudo systemctl enable --now geo-tracker-worker
sudo systemctl status geo-tracker-web geo-tracker-worker
```

**worker 데몬은 절대 두 번 enable하거나 수동으로 추가 실행하지 않는다** —
docs/risk_checklist.md §8 참조(정확히 1개 인스턴스 전제).

프론트엔드(정적 파일)는 별도 웹 서버(nginx 등)로 서빙하거나, 개발/소규모 운영에서는
`python3 -m http.server 5500 --directory frontend`를 systemd 유닛으로 감싸 실행해도 된다.
`frontend/js/api.js`의 `API_BASE`는 프론트엔드가 열린 호스트명 + 8000번 포트로 자동 유도되므로
(`CORS_ORIGINS` 설정과 함께), 실제 도메인/포트에 맞춰 `.env`의 `CORS_ORIGINS`만 조정하면 된다.

## 4. cron 등록

`docs/operations.md` §6 참조 — `geo-tracker` 계정(또는 별도 관리 계정)의 crontab에:

```
0 9 * * MON curl -sf -X POST http://localhost:8000/runs/trigger -H "X-Admin-Api-Key: <ADMIN_API_KEY>" >> /var/log/geo-tracker-trigger.log 2>&1
```

cron은 트리거 API만 호출하고 즉시 끝난다 — CLI 실행은 이미 떠 있는 worker 데몬이 이어받는다.

## 5. 배포 검증 (아키텍처의 핵심 이득을 직접 확인)

배포 직후, systemd 없이 로컬에서도 확인 가능한 핵심 검증:

1. `MOCK_LLM=true`인 상태에서 `POST /runs/trigger`를 호출해 PENDING 잡이 생기는지 확인
   (`pending > 0`, 즉시 응답 — §0 아키텍처의 첫 번째 특징).
2. 몇 초 뒤 `GET /runs/{batch_id}/status`로 worker 데몬이 잡을 집어가 처리했는지 확인
   (`pending == 0`, `success` 건수 증가).
3. **웹 앱 프로세스를 강제 재시작**(`sudo systemctl restart geo-tracker-web`)하면서 배치가
   진행 중이어도 worker 데몬이 계속 실행되는지 확인한다 — `systemctl status geo-tracker-worker`가
   재시작 없이 계속 살아있어야 하고, 배치 상태도 끊기지 않고 이어져야 한다(§0 아키텍처의 핵심
   이득 — Gunicorn 워커 재활용/배포가 배치를 죽이지 않는다).

## 6. 다른 서버로 이전

참고 프로젝트(SQLite, 폴더 복사 기반 이전)와 달리 이 프로젝트는 PostgreSQL이라 파일 복사만으로는
이전되지 않는다:

1. `pg_dump geo_weekly_tracker > backup.sql` (기존 서버)
2. 새 서버에 §1~3 그대로 수행(단, §2의 마이그레이션+시딩 대신 `psql geo_weekly_tracker < backup.sql`로
   복원)
3. `.env`의 CLI 인증 값(`CLAUDE_CODE_OAUTH_TOKEN` 등)은 서버마다 별도로 로그인해야 한다 —
   좌석 인증은 머신에 종속되지 않고 계정에 종속되므로 토큰 자체는 복사해도 되지만, Codex/Gemini
   CLI의 로컬 캐시 자격증명은 안전하게 옮길 수 있는지 사전에 확인한다(민감 정보이므로 전송 경로
   보안에 주의).

## 7. 변경 이력

| 날짜 | 변경 내용 |
|---|---|
| 2026-07-13 | 참고 프로젝트(20260709) STEP 7: 최초 작성 (Windows, 폴더 복사 기반) |
| 2026-07-15 | Flask+PostgreSQL+Ubuntu 재개발: 전면 재작성 — systemd 유닛 2개, cron 트리거, PostgreSQL 백업/복원 기반 이전으로 전환 |
