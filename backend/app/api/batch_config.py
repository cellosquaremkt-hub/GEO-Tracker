"""배치 실행 설정(REPEAT_COUNT) 조회/변경 — 관리자 전용.

관리자가 Settings 화면에서 반복 횟수를 바꾸면 서버 재시작 없이 다음 트리거부터 바로 반영된다
(app/services/batch_config_service.py 참조).
"""

from __future__ import annotations

from flask import Blueprint, jsonify, request

from app.core.security import require_admin_api_key
from app.db.session import get_session
from app.schemas.batch_config import BatchConfigResponse, BatchConfigUpdateRequest
from app.services.batch_config_service import get_repeat_count, update_repeat_count

bp = Blueprint("batch_config", __name__, url_prefix="/batch-config")


@bp.get("")
@require_admin_api_key
def get_batch_config_endpoint():
    session = get_session()
    repeat_count = get_repeat_count(session)
    return jsonify(BatchConfigResponse(repeat_count=repeat_count).model_dump(mode="json"))


@bp.put("")
@require_admin_api_key
def update_batch_config_endpoint():
    payload = BatchConfigUpdateRequest.model_validate(request.get_json(force=True))
    session = get_session()
    repeat_count = update_repeat_count(session, payload.repeat_count)
    return jsonify(BatchConfigResponse(repeat_count=repeat_count).model_dump(mode="json"))
