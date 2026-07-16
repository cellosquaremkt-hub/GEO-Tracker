"""대시보드 상단 카드 지표.

weekly_snapshot을 새로 집계하지 않고 그대로 읽기만 한다 — 집계는 배치가 끝날 때 한 번
app.services.aggregation.aggregate_week()가 전담한다(CLAUDE.md: 도메인 로직과 트리거 계층 분리).
"""

from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.models.brand import Brand
from app.models.enums import ExecutionStatus, Sentiment
from app.models.execution import ExecutionRun, Mention
from app.models.snapshot import WeeklySnapshot
from app.services.week_utils import previous_week_label


@dataclass(frozen=True)
class DashboardSummary:
    week: str
    previous_week: str
    total_sov: Decimal
    rank: int
    total_ranked_entities: int
    sov_delta: Decimal | None
    negative_mention_count: int


def compute_own_sov_sum(session: Session, week: str, own_brand_ids: list[int]) -> Decimal | None:
    """해당 주에 own 브랜드 스냅샷이 하나도 없으면(배치 미실행) None — "비교 불가"를 뜻한다."""
    if not own_brand_ids:
        return Decimal("0")
    rows = (
        session.execute(
            select(WeeklySnapshot.sov).where(
                WeeklySnapshot.week_label == week,
                WeeklySnapshot.llm_provider_id.is_(None),
                WeeklySnapshot.brand_id.in_(own_brand_ids),
            )
        )
        .scalars()
        .all()
    )
    if not rows:
        return None
    return sum(rows, Decimal("0"))


def compute_dashboard_summary(session: Session, week: str) -> DashboardSummary:
    own_brand_ids = list(
        session.execute(select(Brand.id).where(Brand.is_own.is_(True))).scalars().all()
    )

    total_sov = compute_own_sov_sum(session, week, own_brand_ids)
    if total_sov is None:
        total_sov = Decimal("0")

    # 순위: "우리 브랜드(합산)"를 하나의 항목으로, 경쟁사는 개별 SOV로 비교해 순위를 매긴다.
    competitor_sov_rows = list(
        session.execute(
            select(WeeklySnapshot.sov)
            .join(Brand, Brand.id == WeeklySnapshot.brand_id)
            .where(
                WeeklySnapshot.week_label == week,
                WeeklySnapshot.llm_provider_id.is_(None),
                Brand.is_own.is_(False),
            )
        )
        .scalars()
        .all()
    )
    rank = 1 + sum(1 for v in competitor_sov_rows if v > total_sov)

    previous_week = previous_week_label(week)
    previous_total_sov = compute_own_sov_sum(session, previous_week, own_brand_ids)
    sov_delta = None if previous_total_sov is None else total_sov - previous_total_sov

    negative_mention_count = 0
    if own_brand_ids:
        negative_mention_count = session.execute(
            select(func.count())
            .select_from(Mention)
            .join(ExecutionRun, ExecutionRun.id == Mention.execution_run_id)
            .where(
                ExecutionRun.batch_id == week,
                ExecutionRun.status == ExecutionStatus.SUCCESS,
                Mention.brand_id.in_(own_brand_ids),
                Mention.sentiment == Sentiment.NEGATIVE,
            )
        ).scalar_one()

    return DashboardSummary(
        week=week,
        previous_week=previous_week,
        total_sov=total_sov,
        rank=rank,
        total_ranked_entities=1 + len(competitor_sov_rows),
        sov_delta=sov_delta,
        negative_mention_count=negative_mention_count,
    )
