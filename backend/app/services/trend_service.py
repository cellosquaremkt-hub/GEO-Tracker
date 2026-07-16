"""브랜드별 주차 SOV 시계열. 브랜드 수와 무관하게 동작한다 — 트랙 중인 Brand를 그대로 순회한다."""

from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models.brand import Brand
from app.models.snapshot import WeeklySnapshot
from app.services.week_utils import compute_current_week_label, recent_week_labels


@dataclass(frozen=True)
class TrendPoint:
    week: str
    sov: Decimal | None


@dataclass(frozen=True)
class BrandTrend:
    brand_id: int
    brand_name: str
    points: list[TrendPoint]


@dataclass(frozen=True)
class TrendsResult:
    weeks: list[str]
    series: list[BrandTrend]


def compute_trends(session: Session, weeks_count: int, end_week: str | None = None) -> TrendsResult:
    end = end_week or compute_current_week_label()
    week_labels = recent_week_labels(end, weeks_count)

    brands = session.execute(select(Brand.id, Brand.name).order_by(Brand.id)).all()

    snapshot_rows = session.execute(
        select(WeeklySnapshot.brand_id, WeeklySnapshot.week_label, WeeklySnapshot.sov).where(
            WeeklySnapshot.week_label.in_(week_labels),
            WeeklySnapshot.llm_provider_id.is_(None),
        )
    ).all()
    sov_by_brand_week: dict[tuple[int, str], Decimal] = {
        (brand_id, week_label): sov for brand_id, week_label, sov in snapshot_rows
    }

    series = [
        BrandTrend(
            brand_id=brand_id,
            brand_name=brand_name,
            points=[
                TrendPoint(week=w, sov=sov_by_brand_week.get((brand_id, w))) for w in week_labels
            ],
        )
        for brand_id, brand_name in brands
    ]

    return TrendsResult(weeks=week_labels, series=series)
