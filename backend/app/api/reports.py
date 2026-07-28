from __future__ import annotations

from flask import Blueprint, jsonify, request

from app.db.session import get_session
from app.schemas.reports import OwnBrandAnswerResponse, WeeklyReportResponse
from app.services.report_service import compute_weekly_report, get_own_brand_answers
from app.services.week_utils import compute_current_week_label

bp = Blueprint("reports", __name__, url_prefix="/reports")


@bp.get("/weekly")
def get_weekly_report():
    week_label = request.args.get("week") or compute_current_week_label()
    session = get_session()
    report = compute_weekly_report(session, week_label)
    return jsonify(WeeklyReportResponse.model_validate(report).model_dump(mode="json"))


@bp.get("/own-brand")
def get_own_brand_report():
    """brand_type=OWN_BRAND 프롬프트(브랜드명을 직접 묻는 질문)의 이번 주 응답 — weekly_snapshot
    SOV와는 완전히 분리된 별도 섹션이다(app/services/aggregation.py 참조)."""
    week_label = request.args.get("week") or compute_current_week_label()
    session = get_session()
    answers = get_own_brand_answers(session, week_label)
    return jsonify(
        [OwnBrandAnswerResponse.model_validate(a).model_dump(mode="json") for a in answers]
    )
