"""PostgreSQL 전용 동기 엔진 생성.

참고 프로젝트(FastAPI+SQLite)의 create_configured_async_engine()은 SQLite PRAGMA(FK 강제/WAL/
busy_timeout)를 다이얼렉트 분기로 처리했지만, 이 프로젝트는 PostgreSQL만 지원하므로 그 분기
로직 자체가 필요 없다(migration_flask_postgres.md §2.2 참조) — 표준 SQLAlchemy 동기 엔진을
그대로 쓴다.
"""

from __future__ import annotations

from typing import Any

from sqlalchemy import Engine, create_engine


def create_configured_engine(url: str, **kwargs: Any) -> Engine:
    return create_engine(url, **kwargs)
