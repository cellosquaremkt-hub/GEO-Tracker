"""ISO 주차 문자열("2026-W28") 계산 유틸 — batch_runner와 조회 API가 공유하는 단일 진실 원천.

execution_run.batch_id와 weekly_snapshot.week_label은 이 형식을 공유한다 (docs/metrics.md §0).
"""

from __future__ import annotations

from datetime import date, datetime, timedelta
from zoneinfo import ZoneInfo

from app.core.config import settings

_WEEK_LABEL_FORMAT = "{year}-W{week:02d}"


def _label_for_date(d: date) -> str:
    iso_year, iso_week, _ = d.isocalendar()
    return _WEEK_LABEL_FORMAT.format(year=iso_year, week=iso_week)


def _monday_of_week(week_label: str) -> date:
    year_str, week_str = week_label.split("-W")
    return date.fromisocalendar(int(year_str), int(week_str), 1)


def compute_current_week_label(now: datetime | None = None) -> str:
    tz = ZoneInfo(settings.app_timezone)
    moment = now or datetime.now(tz)
    return _label_for_date(moment.date())


def previous_week_label(week_label: str) -> str:
    monday = _monday_of_week(week_label)
    return _label_for_date(monday - timedelta(days=7))


def recent_week_labels(end_week: str, count: int) -> list[str]:
    """end_week를 포함해 과거로 count개의 주차 라벨을 오름차순으로 반환한다."""
    if count < 1:
        raise ValueError("count는 1 이상이어야 합니다.")
    monday = _monday_of_week(end_week)
    labels = [_label_for_date(monday - timedelta(weeks=offset)) for offset in range(count)]
    return list(reversed(labels))
