from __future__ import annotations

from flask import Blueprint, jsonify, request

from app.db.session import get_session
from app.schemas.reports import WeeklyReportResponse
from app.services.report_service import compute_weekly_report
from app.services.week_utils import compute_current_week_label

bp = Blueprint("reports", __name__, url_prefix="/reports")


@bp.get("/weekly")
def get_weekly_report():
    week_label = request.args.get("week") or compute_current_week_label()
    session = get_session()
    report = compute_weekly_report(session, week_label)
    return jsonify(WeeklyReportResponse.model_validate(report).model_dump(mode="json"))
