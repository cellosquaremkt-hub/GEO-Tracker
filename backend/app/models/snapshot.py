from __future__ import annotations

from decimal import Decimal

from sqlalchemy import ForeignKey, Index, Integer, Numeric, String, UniqueConstraint, text
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base


class WeeklySnapshot(Base):
    """주간 집계. llm_provider_id가 null이면 전체 프로바이더 합산 행이다.

    sov는 언급이 전혀 없는 주에도 0으로 정의되지만(분모가 0인 극단 상황을 관례로 처리),
    avg_rank / sentiment_*_pct / citation_share_pct는 해당 브랜드의 언급·인용이 하나도 없으면
    평균/비율 자체가 정의되지 않으므로 null이다. 계산식 전문은 docs/metrics.md 참조.
    """

    __tablename__ = "weekly_snapshot"
    __table_args__ = (
        # llm_provider_id가 NOT NULL인 행: 주+브랜드+프로바이더 조합당 하나.
        UniqueConstraint(
            "week_label",
            "brand_id",
            "llm_provider_id",
            name="uq_weekly_snapshot_week_brand_provider",
        ),
        # llm_provider_id가 NULL(전체 합산)인 행: UNIQUE 제약에서 NULL을 서로 다른 값으로
        # 취급하므로 위 제약만으로는 중복 전체합산 행을 막지 못한다. 부분 유니크 인덱스로
        # 보강한다(PostgreSQL 전용 프로젝트라 postgresql_where만 지정 — 참고 프로젝트는 SQLite도
        # 지원해야 해서 sqlite_where를 같이 뒀었다. migration_flask_postgres.md §2.2 참조).
        Index(
            "uq_weekly_snapshot_week_brand_all_providers",
            "week_label",
            "brand_id",
            unique=True,
            postgresql_where=text("llm_provider_id IS NULL"),
        ),
        # /trends, /dashboard/summary가 "이 브랜드의 전체합산 SOV를 최근 N주 조회"하는 패턴 —
        # brand_id를 선행 컬럼으로 둔 커버링 인덱스로 브랜드별 시계열 스캔을 돕는다.
        Index(
            "ix_weekly_snapshot_brand_provider_week", "brand_id", "llm_provider_id", "week_label"
        ),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    # 예: "2026-W28"
    week_label: Mapped[str] = mapped_column(String(20), nullable=False, index=True)
    brand_id: Mapped[int] = mapped_column(ForeignKey("brand.id"), nullable=False, index=True)
    llm_provider_id: Mapped[int | None] = mapped_column(
        ForeignKey("llm_provider.id"), nullable=True, index=True
    )
    sov: Mapped[Decimal] = mapped_column(Numeric(6, 3), nullable=False)
    avg_rank: Mapped[Decimal | None] = mapped_column(Numeric(6, 3), nullable=True)
    sentiment_positive_pct: Mapped[Decimal | None] = mapped_column(Numeric(6, 3), nullable=True)
    sentiment_neutral_pct: Mapped[Decimal | None] = mapped_column(Numeric(6, 3), nullable=True)
    sentiment_negative_pct: Mapped[Decimal | None] = mapped_column(Numeric(6, 3), nullable=True)
    citation_share_pct: Mapped[Decimal | None] = mapped_column(Numeric(6, 3), nullable=True)
    # 이 스냅샷을 계산할 때 분모로 사용한 execution_run 개수 (감사/재현용 기록).
    total_runs: Mapped[int] = mapped_column(Integer, nullable=False)

    brand: Mapped[Brand] = relationship()  # noqa: F821
    llm_provider: Mapped[LLMProvider | None] = relationship()  # noqa: F821
