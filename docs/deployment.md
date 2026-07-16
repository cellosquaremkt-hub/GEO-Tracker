# 배포 절차 (Ubuntu)

이 문서는 GEO Weekly Tracker(Flask + PostgreSQL + Gunicorn + worker 데몬)를 Ubuntu 서버에
배포하는 절차를 다룬다. 참고 프로젝트(20260709, Windows+SQLite)의 `docs/deployment.md`(폴더
복사 기반 이전)와는 전제 자체가 다르므로 완전히 새로 작성됐다.

**현재 운영 방식(2026-07-16 기준): 보안 정책상 서버가 외부 GitHub에 직접 연결되지 않는다.**
그래서 코드는 "이 PC에서 파일을 내려받아 담당자에게 전달 → 담당자가 서버에 직접 설치"하는
방식으로 옮긴다(§2 참조). 사내 전용 GitHub이 준비되면(아직 미착수) 그쪽에 푸시하고 서버가
그걸 당겨오는 방식(`git pull` 또는 CI/CD)으로 전환할 수 있지만, **지금은 아직 그렇게 운영되지
않는다** — 이 문서의 §2는 그 전환 전 단계인 수동 파일 전달 기준으로 작성했다.

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

## 2. 코드 배포 (파일 전달 방식 — 현재 운영 방식)

### 2.1 이 PC에서: 전달용 압축 파일 만들기

로컬에 이미 git 저장소가 있으므로, `git archive`를 쓰면 `.gitignore`에 걸린 것들(`.venv/`,
`__pycache__/`, `.env`, 캐시 디렉터리 등)이 자동으로 빠진 깨끗한 압축 파일이 만들어진다 —
수동으로 뭘 지우거나 골라낼 필요가 없다.

```powershell
cd "C:\자료\작업중\geo-tracker-flask"
git archive --format=zip -o geo-tracker-flask.zip HEAD
```

`geo-tracker-flask.zip`이 생성된다 — 이 파일을 담당자에게 전달한다(사내 파일 공유/USB/메일
등, 회사 보안 정책에 맞는 경로로).

**`.env`는 이 zip에 포함되지 않는다(의도적 — 비밀번호/키가 든 파일을 그대로 전달하면 안 된다).**
필요한 값들(§2.3 참조)은 담당자에게 **별도의 보안 채널**(사내 메신저 DM, 비밀번호 관리 도구 등)로
전달하거나, 담당자가 서버에서 직접 값을 새로 발급받는다(예: `ADMIN_API_KEY`는 새로 아무 값이나
정해도 되고, DB 비밀번호도 서버에서 새로 정해도 된다 — 반드시 이 PC와 같은 값일 필요는 없다).

### 2.2 담당자가 서버에서: 압축 해제 + 설치

```bash
sudo mkdir -p /opt/geo-tracker-flask
sudo chown geo-tracker:geo-tracker /opt/geo-tracker-flask
# geo-tracker-flask.zip을 서버의 /opt/geo-tracker-flask 위치에 옮겨둔 뒤:
cd /opt/geo-tracker-flask
sudo -u geo-tracker unzip geo-tracker-flask.zip
cd backend
sudo -u geo-tracker python3.11 -m venv .venv
sudo -u geo-tracker .venv/bin/pip install -e .
```

### 2.3 `.env` 준비 (서버에서 직접 값 채움)

```bash
cd /opt/geo-tracker-flask
sudo -u geo-tracker cp .env.example .env
sudo -u geo-tracker nano .env
```

채워야 할 값:
- `DATABASE_URL`/`TEST_DATABASE_URL`: §1.5에서 만든 PostgreSQL 접속 정보
- `ADMIN_API_KEY`: 아무 임의의 강력한 문자열(관리자 API 인증용 — 프론트엔드 Settings 화면에도
  같은 값을 입력해야 함)
- CLI 인증(`CLAUDE_CODE_OAUTH_TOKEN` 등)은 `.env`에 직접 쓰지 않는다 — §1.4대로 서버에서 CLI
  로그인을 완료하면 OS 사용자 환경에 남는다(자세한 이유는 docs/operations.md §0 참조)

DB 마이그레이션 + 시딩:

```bash
cd /opt/geo-tracker-flask/backend
sudo -u geo-tracker .venv/bin/python -m alembic upgrade head
sudo -u geo-tracker .venv/bin/python -m app.db.seed
```

### 2.4 업데이트(코드가 바뀐 뒤 다시 배포할 때)

지금 방식(사내 GitHub 미연동)에서는 업데이트도 매번 §2.1~2.2를 반복한다 — 이 PC에서
`git archive`로 새 zip을 만들고, 담당자가 받아서 **기존 `/opt/geo-tracker-flask` 폴더의
코드만 덮어쓴다**(`.env`와 PostgreSQL 데이터는 그대로 둔다):

```bash
# 담당자가 서버에서 — 기존 .env는 안전하게 보존한 채 코드만 교체
cd /opt/geo-tracker-flask
sudo -u geo-tracker unzip -o new-geo-tracker-flask.zip   # -o: 기존 파일 덮어쓰기, .env는 zip에 없으므로 안 건드려짐
sudo systemctl restart geo-tracker-web
# worker 데몬은 배치가 진행 중이 아닐 때 재시작한다(§0 아키텍처 참조 — 진행 중이어도 죽지는
# 않지만, 재시작하면 그 순간 실행 중이던 CLI 호출은 중단된다)
sudo systemctl restart geo-tracker-worker
```

DB 스키마가 바뀐 배포라면(`alembic/versions/`에 새 파일이 있으면) 재시작 전에
`sudo -u geo-tracker .venv/bin/python -m alembic upgrade head`를 먼저 실행한다.

**나중에(사내 GitHub 연동 이후)**: 이 §2 전체가 `git clone`/`git pull` 한 줄로 단순화된다 —
서버가 사내 GitHub에서 직접 코드를 받아올 수 있게 되면, 코드 전달을 위해 사람이 파일을 옮길
필요가 없어진다. 지금은 아직 그 단계가 아니므로 위 수동 절차를 따른다.

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

## 8. 문제 해결 — 서버 직접 접근이 없을 때의 원격 진단

로컬 PC에서 개발할 때는 PowerShell/Bash에 직접 명령어를 쳐서 무엇이 문제인지 바로 확인할 수
있었다. 서버에 배포한 뒤에는 그 방식 자체가 없어지는 게 아니라 **누가 그 터미널 접근 권한을
갖는지가 바뀔 뿐이다** — Ubuntu 서버에서는 PowerShell 대신 SSH로 접속한 bash 터미널이 같은
역할을 한다. 문제는 지금 운영 구조상 **이 PC를 쓰는 사람(관리자)이 서버에 직접 접근하지 못하고,
담당자만 접근 가능하다는 점**이다 — 그래서 진단은 "담당자에게 어떤 명령어를 실행해서 결과를
보내달라고 요청하는" 방식으로 이루어진다. 아래는 증상별로 담당자에게 그대로 전달할 수 있는
명령어 모음이다.

### 8.1 관리자 PC에서 직접 확인 가능한 것 (터미널 접근 없이도 가능)

사내망에서 서버의 8000번 포트(API)에 접근이 허용되어 있다면, **터미널 접근 없이 브라우저나
`curl`만으로도** 아래는 직접 확인할 수 있다 — 담당자에게 요청할 필요조차 없는 1차 점검:

```
http://<서버 IP 또는 도메인>:8000/health          → {"status": "ok"} 가 떠야 정상
http://<서버 IP 또는 도메인>:8000/dashboard/summary → 대시보드 데이터가 JSON으로 떠야 정상
```

프론트엔드가 서비스되고 있다면 브라우저로 실제 화면(대시보드)을 열어보는 것도 유효한 1차
점검이다 — 화면이 뜨고 데이터가 보이면 웹 앱과 DB 연결은 정상이라는 뜻이다.

### 8.2 증상별 — 담당자에게 요청할 명령어

**"화면/API가 아예 안 열려요" (웹 앱이 죽어있는지 확인)**

```bash
sudo systemctl status geo-tracker-web
sudo journalctl -u geo-tracker-web -n 100 --no-pager
```
`Active: active (running)`이 아니면 죽어있는 것 — 로그 마지막 부분에 에러 메시지가 있을
것이다. `sudo systemctl restart geo-tracker-web`으로 재시작해볼 수 있다(§0 아키텍처상 이
재시작은 배치 실행에 영향을 주지 않으므로 안전하다).

**"주간 실행을 눌러도 계속 대기(pending) 상태예요" (worker 데몬이 죽어있는지 확인)**

```bash
sudo systemctl status geo-tracker-worker
sudo journalctl -u geo-tracker-worker -n 100 --no-pager
```
worker 데몬이 안 떠 있으면(`Active`가 running이 아니면) 이게 원인이다 — `sudo systemctl
restart geo-tracker-worker`로 재시작. 떠 있는데도 안 되면 로그에서 `MissingAPIKeyError`(CLI
로그인 만료 — docs/operations.md §1~4 재인증 필요) 또는 `CLIRateLimitError`(구독 좌석 사용량
한도 — 사람 개입 불필요, 기다리면 풀림)를 찾아본다.

**"일부만 실패했어요" (개별 실행 건 원인 확인)**

```bash
sudo -u geo-tracker psql geo_weekly_tracker -c "SELECT id, llm_provider_id, status, error_message FROM execution_run WHERE batch_id = '<주차, 예: 2026-W29>' AND status = 'failed';"
```

**"DB 연결 자체가 안 되는 것 같아요"**

```bash
sudo -u geo-tracker psql -h localhost -U geo geo_weekly_tracker -c "\dt"
```
테이블 목록이 나오면 DB 연결은 정상 — 안 나오면 PostgreSQL 서비스 자체(`sudo systemctl status
postgresql`) 또는 `.env`의 `DATABASE_URL` 값을 의심한다.

### 8.3 실무 팁

- 담당자에게 "안 돼요"라는 보고만 받으면 원인을 좁힐 수 없다 — **위 표 중 증상에 맞는 명령어의
  출력 전체를 캡처(스크린샷/복사)해서 보내달라고** 요청하는 것을 표준 절차로 삼는 것을 권장한다.
- 배포 초기에는 담당자에게 이 문서(§8) 자체를 전달해 스스로 1차 점검을 해보도록 안내하는 것도
  좋다 — 매번 관리자에게 되묻지 않고 담당자 선에서 재시작 정도는 해결할 수 있다.
- 장기적으로는 담당자(또는 관리자)가 서버에 제한된 SSH 접근 권한(예: `journalctl`/`systemctl
  status`만 가능한 계정)을 갖는 것을 사내 IT와 협의해볼 가치가 있다 — 매번 명령어를 대신
  실행해달라고 요청하는 것보다 훨씬 빠르게 진단할 수 있다.

## 9. 변경 이력

| 날짜 | 변경 내용 |
|---|---|
| 2026-07-13 | 참고 프로젝트(20260709) STEP 7: 최초 작성 (Windows, 폴더 복사 기반) |
| 2026-07-15 | Flask+PostgreSQL+Ubuntu 재개발: 전면 재작성 — systemd 유닛 2개, cron 트리거, PostgreSQL 백업/복원 기반 이전으로 전환 |
| 2026-07-16 | §2를 파일 전달 방식(현재 실제 운영 방식 — 사내 GitHub 미연동)으로 재작성, §8 원격 진단 가이드 신규 추가 |
