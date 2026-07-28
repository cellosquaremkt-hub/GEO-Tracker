"""주간 집계 — docs/metrics.md 정의를 그대로 구현한다.

계산 로직(calculate_snapshot_metrics)은 DB 접근이 없는 순수 함수로 분리해 단위 테스트한다.
aggregate_week()가 실제 쿼리로 분자/분모를 모아 그 순수 함수에 넘기고, 결과를 WeeklySnapshot으로
저장한다. 코드와 docs/metrics.md가 어긋나면 docs/metrics.md를 기준으로 이 파일을 고친다.
"""

from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass
from decimal import ROUND_HALF_UP, Decimal

from sqlalchemy import delete, func, select
from sqlalchemy.orm import Session

from app.models.brand import Brand
from app.models.enums import BrandType, ExecutionStatus, Sentiment
from app.models.execution import Citation, ExecutionRun, Mention
from app.models.llm_provider import LLMProvider
from app.models.prompt import Prompt
from app.models.snapshot import WeeklySnapshot

_QUANT = Decimal("0.001")


@dataclass(frozen=True)
class SnapshotMetrics:
    sov: Decimal
    avg_rank: Decimal | None
    sentiment_positive_pct: Decimal | None
    sentiment_neutral_pct: Decimal | None
    sentiment_negative_pct: Decimal | None
    citation_share_pct: Decimal | None


def _pct_or_none(numerator: int, denominator: int) -> Decimal | None:
    if denominator <= 0:
        return None
    return (Decimal(numerator) / Decimal(denominator) * 100).quantize(
        _QUANT, rounding=ROUND_HALF_UP
    )


def calculate_snapshot_metrics(
    *,
    mention_count: int,
    total_mentions: int,
    mention_order_sum: int,
    sentiment_counts: dict[Sentiment, int],
    brand_citations: int,
    total_citations: int,
) -> SnapshotMetrics:
    """docs/metrics.md §1~4의 분자/분모 정의를 그대로 옮긴 순수 함수.

    - sov: total_mentions=0(스코프에 어떤 브랜드도 언급 안 됨)이면 0으로 정의(NOT NULL, 관례).
      그 외에는 mention_count=0이어도 0/total*100=0으로 자연스럽게 계산된다.
    - avg_rank / sentiment_*_pct / citation_share_pct: 각자의 분모(mention_count 또는
      total_citations)가 0이면 정의되지 않으므로 None.
    """
    sov = _pct_or_none(mention_count, total_mentions)
    if sov is None:
        sov = Decimal("0.000")

    avg_rank = None
    if mention_count > 0:
        avg_rank = (Decimal(mention_order_sum) / Decimal(mention_count)).quantize(
            _QUANT, rounding=ROUND_HALF_UP
        )

    return SnapshotMetrics(
        sov=sov,
        avg_rank=avg_rank,
        sentiment_positive_pct=_pct_or_none(
            sentiment_counts.get(Sentiment.POSITIVE, 0), mention_count
        ),
        sentiment_neutral_pct=_pct_or_none(
            sentiment_counts.get(Sentiment.NEUTRAL, 0), mention_count
        ),
        sentiment_negative_pct=_pct_or_none(
            sentiment_counts.get(Sentiment.NEGATIVE, 0), mention_count
        ),
        citation_share_pct=_pct_or_none(brand_citations, total_citations),
    )


def _compute_scope_snapshots(
    session: Session,
    week_label: str,
    llm_provider_id: int | None,
    brand_ids: list[int],
) -> list[WeeklySnapshot]:
    # brand_type=OWN_BRAND(자사 브랜드를 직접 묻는 질문)는 그 브랜드 언급률이 구조적으로
    # 100%에 가깝기 때문에 SOV 분자/분모 어디에도 넣지 않는다(CLAUDE.md, prompt.py 참조).
    # 별도 조회는 report_service.get_own_brand_answers() 참조.
    run_scope = (
        select(ExecutionRun.id)
        .join(Prompt, Prompt.id == ExecutionRun.prompt_id)
        .where(
            ExecutionRun.batch_id == week_label,
            ExecutionRun.status == ExecutionStatus.SUCCESS,
            Prompt.brand_type.is_distinct_from(BrandType.OWN_BRAND),
        )
    )
    if llm_provider_id is not None:
        run_scope = run_scope.where(ExecutionRun.llm_provider_id == llm_provider_id)
    run_scope_subq = run_scope.subquery()
    run_ids = select(run_scope_subq.c.id)

    total_runs = session.execute(select(func.count()).select_from(run_scope_subq)).scalar_one()

    mention_counts: dict[int, int] = dict(
        session.execute(
            select(Mention.brand_id, func.count())
            .where(Mention.execution_run_id.in_(run_ids))
            .group_by(Mention.brand_id)
        ).all()
    )
    total_mentions = sum(mention_counts.values())

    order_sums: dict[int, int] = {
        brand_id: int(total)
        for brand_id, total in session.execute(
            select(Mention.brand_id, func.sum(Mention.mention_order))
            .where(Mention.execution_run_id.in_(run_ids))
            .group_by(Mention.brand_id)
        ).all()
    }

    sentiment_by_brand: dict[int, dict[Sentiment, int]] = defaultdict(dict)
    for brand_id, sentiment, count in session.execute(
        select(Mention.brand_id, Mention.sentiment, func.count())
        .where(Mention.execution_run_id.in_(run_ids))
        .group_by(Mention.brand_id, Mention.sentiment)
    ).all():
        sentiment_by_brand[brand_id][sentiment] = count

    total_citations = session.execute(
        select(func.count()).select_from(Citation).where(Citation.execution_run_id.in_(run_ids))
    ).scalar_one()
    citation_counts: dict[int, int] = dict(
        session.execute(
            select(Citation.matched_brand_id, func.count())
            .where(Citation.execution_run_id.in_(run_ids), Citation.matched_brand_id.is_not(None))
            .group_by(Citation.matched_brand_id)
        ).all()
    )

    snapshots = []
    for brand_id in brand_ids:
        metrics = calculate_snapshot_metrics(
            mention_count=mention_counts.get(brand_id, 0),
            total_mentions=total_mentions,
            mention_order_sum=order_sums.get(brand_id, 0),
            sentiment_counts=sentiment_by_brand.get(brand_id, {}),
            brand_citations=citation_counts.get(brand_id, 0),
            total_citations=total_citations,
        )
        snapshots.append(
            WeeklySnapshot(
                week_label=week_label,
                brand_id=brand_id,
                llm_provider_id=llm_provider_id,
                sov=metrics.sov,
                avg_rank=metrics.avg_rank,
                sentiment_positive_pct=metrics.sentiment_positive_pct,
                sentiment_neutral_pct=metrics.sentiment_neutral_pct,
                sentiment_negative_pct=metrics.sentiment_negative_pct,
                citation_share_pct=metrics.citation_share_pct,
                total_runs=total_runs,
            )
        )
    return snapshots


def aggregate_week(session: Session, week_label: str) -> list[WeeklySnapshot]:
    """week_label의 (브랜드 x 프로바이더) + (브랜드 x 전체합산) 스냅샷을 계산하고 교체 저장한다."""
    brand_ids = session.execute(select(Brand.id)).scalars().all()
    provider_ids = (
        session.execute(select(LLMProvider.id).where(LLMProvider.is_active.is_(True)))
        .scalars()
        .all()
    )

    snapshots: list[WeeklySnapshot] = []
    snapshots.extend(_compute_scope_snapshots(session, week_label, None, list(brand_ids)))
    for provider_id in provider_ids:
        snapshots.extend(
            _compute_scope_snapshots(session, week_label, provider_id, list(brand_ids))
        )

    # 같은 week_label 재집계 시 기존 snapshot을 교체한다 (전면 재계산이므로 delete+insert가
    # 부분 유니크 인덱스가 걸린 ON CONFLICT보다 단순하고 확실하다).
    session.execute(delete(WeeklySnapshot).where(WeeklySnapshot.week_label == week_label))
    session.add_all(snapshots)
    session.commit()
    return snapshots
