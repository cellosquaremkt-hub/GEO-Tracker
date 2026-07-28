"""GEO Weekly Tracker API 앱 팩토리 (Flask + Gunicorn, WSGI/동기).

로컬 개발 실행: flask --app app.main run  (backend/ 에서, venv 활성화 후)
운영 실행: gunicorn -c gunicorn.conf.py app.main:app

이 프로세스는 CLI(Claude Code/Codex/Gemini) 서브프로세스를 절대 직접 실행하지 않는다 — 그건
app/worker/daemon.py(별도 프로세스)의 역할이다. 이 웹 앱은 배치 실행 요청을 DB에 PENDING으로
기록만 하고 즉시 응답한다(docs/migration_flask_postgres.md §2.3 참조 — Gunicorn의 멀티 워커
프로세스 모델과 장시간 백그라운드 작업이 충돌하는 문제를 피하기 위한 설계).
"""

from __future__ import annotations

import logging

from flask import Flask, jsonify
from flask_cors import CORS
from pydantic import ValidationError

from app.core.config import settings
from app.db.session import init_session_teardown

logging.basicConfig(level=settings.log_level)


def create_app() -> Flask:
    app = Flask(__name__)
    init_session_teardown(app)

    cors_origins = [origin.strip() for origin in settings.cors_origins.split(",") if origin.strip()]
    if cors_origins:
        CORS(app, origins=cors_origins, supports_credentials=True)

    @app.errorhandler(ValidationError)
    def handle_validation_error(exc: ValidationError):
        # FastAPI가 요청 바디 검증 실패 시 자동으로 422를 내려주던 것과 동일한 동작을 재현한다
        # (schemas/*.py의 Pydantic 모델은 그대로 재사용하되, Flask는 이 자동 변환이 없다).
        return jsonify({"detail": exc.errors()}), 422

    @app.get("/health")
    def health() -> dict[str, str]:
        return {"status": "ok"}

    from app.api.batch_config import bp as batch_config_bp
    from app.api.brands import bp as brands_bp
    from app.api.dashboard import bp as dashboard_bp
    from app.api.export import bp as export_bp
    from app.api.llm_providers import bp as llm_providers_bp
    from app.api.mentions import bp as mentions_bp
    from app.api.prompts import bp as prompts_bp
    from app.api.reports import bp as reports_bp
    from app.api.runs import bp as runs_bp
    from app.api.trends import bp as trends_bp

    for blueprint in (
        dashboard_bp,
        brands_bp,
        export_bp,
        llm_providers_bp,
        mentions_bp,
        prompts_bp,
        reports_bp,
        runs_bp,
        trends_bp,
        batch_config_bp,
    ):
        app.register_blueprint(blueprint)

    return app


app = create_app()
