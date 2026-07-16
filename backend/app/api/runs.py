"""수동 배치 트리거/재개/상태 조회 — 전부 ADMIN_API_KEY 인증이 필요하다.

**이 모듈은 app/llm_clients/를 import하지 않는다** — trigger_batch()/resume_batch()는
execution_run을 PENDING으로 만들거나 되돌리기만 하고 즉시 반환한다. 실제 CLI 실행은
app/worker/daemon.py(별도 프로세스)가 전담한다(migration_flask_postgres.md §2.3, §2.5).
"""

from __future__ import annotations

from flask import Blueprint, jsonify

from app.core.security import require_admin_api_key
from app.db.session import get_session
from app.schemas.runs import BatchStatusResponse
from app.services.batch_runner import (
    BatchNotFoundError,
    BatchTooLargeError,
    get_batch_status,
    resume_batch,
    trigger_batch,
)

bp = Blueprint("runs", __name__, url_prefix="/runs")


@bp.post("/trigger")
@require_admin_api_key
def trigger_run():
    session = get_session()
    try:
        result = trigger_batch(session)
    except BatchTooLargeError as exc:
        return jsonify({"detail": str(exc)}), 400
    return jsonify(BatchStatusResponse.model_validate(result).model_dump(mode="json"))


@bp.post("/<batch_id>/resume")
@require_admin_api_key
def resume_run(batch_id: str):
    session = get_session()
    try:
        result = resume_batch(session, batch_id)
    except BatchNotFoundError as exc:
        return jsonify({"detail": str(exc)}), 404
    return jsonify(BatchStatusResponse.model_validate(result).model_dump(mode="json"))


@bp.get("/<batch_id>/status")
@require_admin_api_key
def get_run_status(batch_id: str):
    session = get_session()
    result = get_batch_status(session, batch_id)
    if result.pending + result.running + result.success + result.failed == 0:
        return jsonify(
            {"detail": f"batch_id '{batch_id}'에 해당하는 execution_run이 없습니다."}
        ), 404
    return jsonify(BatchStatusResponse.model_validate(result).model_dump(mode="json"))
