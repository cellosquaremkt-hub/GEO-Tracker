from __future__ import annotations

from flask import Blueprint, jsonify, request

from app.db.session import get_session
from app.schemas.mentions import MentionRowResponse
from app.services.export_service import fetch_mention_rows
from app.services.week_utils import compute_current_week_label

bp = Blueprint("mentions", __name__, url_prefix="/mentions")


@bp.get("")
def list_mentions_endpoint():
    """주간 전체 mention을 한 번에 반환한다 — 프론트가 활성 프롬프트마다
    GET /prompts/{id}/detail을 개별 호출하던 N+1 패턴(weekData.js)을 대체한다."""
    week_label = request.args.get("week") or compute_current_week_label()
    session = get_session()
    rows = fetch_mention_rows(session, week_label)
    return jsonify([MentionRowResponse.model_validate(row).model_dump(mode="json") for row in rows])
