import tempfile
from pathlib import Path

from pydantic_settings import BaseSettings, SettingsConfigDict

# 저장소 루트 — .env 하나를 backend/worker/scripts가 공유한다(참고 프로젝트 CLAUDE.md 폴더
# 구조와 동일한 관례. C:\자료\작업중\20260709는 이 재개발의 참고용 원본 — docs/
# migration_flask_postgres.md 참조).
_REPO_ROOT = Path(__file__).resolve().parents[3]
_REPO_ROOT_ENV = _REPO_ROOT / ".env"
_DEFAULT_CLI_WORKDIR = str(Path(tempfile.gettempdir()) / "geo-tracker-workdir")


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=_REPO_ROOT_ENV, env_file_encoding="utf-8", extra="ignore"
    )

    environment: str = "development"
    log_level: str = "INFO"
    app_timezone: str = "Asia/Seoul"
    admin_api_key: str = "change-me-in-production"
    cors_origins: str = ""

    # PostgreSQL 전용(참고 프로젝트의 SQLite 폴백은 이번 재개발에서 제거됨 —
    # migration_flask_postgres.md §2.2 참조). 로컬 개발용 기본값은 표준 psycopg 동기 드라이버
    # 접속 문자열 형태만 예시로 두고, 실제 값은 .env에서 반드시 채운다.
    database_url: str = (
        "postgresql+psycopg://geo:geo_dev_password@localhost:5432/geo_weekly_tracker"
    )
    test_database_url: str | None = (
        "postgresql+psycopg://geo:geo_dev_password@localhost:5432/geo_weekly_tracker_test"
    )

    mock_llm: bool = True
    repeat_count: int = 3
    weekly_batch_cron: str = "0 9 * * MON"

    # --- CLI 기반 측정 (Phase 3/4에서 사용 — docs/llm_clis.md 참조) ---
    cli_workdir: str = _DEFAULT_CLI_WORKDIR
    cli_timeout_sec: float = 180.0
    max_calls_per_batch: int = 300

    # 프로바이더별 동시 실행 상한. worker 데몬 프로세스 하나 안에서만 의미를 갖는다(§2.3 참조 —
    # 여러 프로세스에 걸쳐 나뉘지 않으므로 이 값이 곧 실제 상한이다).
    claude_code_concurrency_limit: int = 1
    codex_concurrency_limit: int = 1
    gemini_cli_concurrency_limit: int = 2

    # worker 데몬이 PENDING 잡을 폴링하는 간격(초) — migration_flask_postgres.md §2.3/Phase 4.
    worker_poll_interval_sec: float = 3.0


settings = Settings()
