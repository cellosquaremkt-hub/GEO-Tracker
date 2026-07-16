from __future__ import annotations

from flask import Blueprint, jsonify, request

from app.db.session import get_session
from app.schemas.trends import TrendsResponse
from app.services.trend_service import compute_trends

bp = Blueprint("trends", __name__, url_prefix="/trends")


@bp.get("")
def get_trends():
    weeks = int(request.args.get("weeks", 8))
    if not (1 <= weeks <= 52):
        return jsonify({"detail": "weeks는 1~52 사이여야 합니다."}), 422
    week = request.args.get("week")
    session = get_session()
    result = compute_trends(session, weeks, end_week=week)
    return jsonify(TrendsResponse.model_validate(result).model_dump(mode="json"))
