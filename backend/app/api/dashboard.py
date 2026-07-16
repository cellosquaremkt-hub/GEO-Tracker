from __future__ import annotations

from flask import Blueprint, jsonify, request

from app.db.session import get_session
from app.schemas.dashboard import DashboardSummaryResponse
from app.services.dashboard_service import compute_dashboard_summary
from app.services.week_utils import compute_current_week_label

bp = Blueprint("dashboard", __name__, url_prefix="/dashboard")


@bp.get("/summary")
def get_dashboard_summary():
    week_label = request.args.get("week") or compute_current_week_label()
    session = get_session()
    summary = compute_dashboard_summary(session, week_label)
    return jsonify(DashboardSummaryResponse.model_validate(summary).model_dump(mode="json"))
