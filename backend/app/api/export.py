from __future__ import annotations

from flask import Blueprint, Response, request

from app.db.session import get_session
from app.services.export_service import build_mention_csv
from app.services.week_utils import compute_current_week_label

bp = Blueprint("export", __name__, url_prefix="/export")


@bp.get("/csv")
def export_csv():
    week_label = request.args.get("week") or compute_current_week_label()
    session = get_session()
    csv_text = build_mention_csv(session, week_label)
    return Response(
        csv_text,
        mimetype="text/csv",
        headers={"Content-Disposition": f'attachment; filename="geo_export_{week_label}.csv"'},
    )
