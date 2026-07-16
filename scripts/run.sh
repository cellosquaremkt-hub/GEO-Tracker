#!/usr/bin/env bash
# 개발용 실행: 웹 앱(gunicorn)과 프론트엔드 정적 서버를 각각 백그라운드로 띄운다.
# 운영 배포에서는 이 스크립트 대신 systemd 유닛 2개(웹 앱, worker 데몬)를 쓴다
# (docs/migration_flask_postgres.md Phase 7 참조). 이 스크립트는 worker 데몬을 띄우지
# 않는다 — 배치 실행까지 확인하려면 별도 터미널에서
# `backend/.venv/bin/python -m app.worker.daemon`을 직접 실행할 것(Phase 4 이후).
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
BACKEND_DIR="$SCRIPT_DIR/../backend"
FRONTEND_DIR="$SCRIPT_DIR/../frontend"

echo "=== GEO Weekly Tracker (Flask) 개발 서버 시작 ==="
echo "  API:      http://127.0.0.1:8000"
echo "  Frontend: http://127.0.0.1:5500"

cd "$BACKEND_DIR"
.venv/bin/gunicorn -c gunicorn.conf.py app.main:app &
GUNICORN_PID=$!

cd "$FRONTEND_DIR"
python3 -m http.server 5500 &
FRONTEND_PID=$!

echo "gunicorn PID: $GUNICORN_PID, frontend PID: $FRONTEND_PID"
echo "종료하려면: kill $GUNICORN_PID $FRONTEND_PID"
wait
