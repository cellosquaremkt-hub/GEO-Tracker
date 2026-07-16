#!/usr/bin/env bash
# 최초 1회 실행: venv 생성 + 의존성 설치 + DB 마이그레이션 + 시딩.
# docs/migration_flask_postgres.md Phase 0 참조.
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
BACKEND_DIR="$SCRIPT_DIR/../backend"

cd "$BACKEND_DIR"

if [ ! -d ".venv" ]; then
  echo "=== venv 생성 ==="
  python3 -m venv .venv
fi

echo "=== 의존성 설치 ==="
.venv/bin/pip install --upgrade pip -q
.venv/bin/pip install -e ".[dev]" -q

if [ ! -f "../.env" ]; then
  echo "=== .env 없음 — .env.example에서 복사 ==="
  cp ../.env.example ../.env
fi

echo "=== DB 마이그레이션 (alembic upgrade head) ==="
.venv/bin/alembic upgrade head

echo "=== 초기 데이터 시딩 ==="
.venv/bin/python -m app.db.seed

echo "=== 완료 ==="
