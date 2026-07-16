from __future__ import annotations

from datetime import datetime
from decimal import Decimal

from sqlalchemy import (
    CheckConstraint,
    DateTime,
    Enum,
    ForeignKey,
    Index,
    Integer,
    Numeric,
    String,
    Text,
    UniqueConstraint,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base
from app.models.enums import ExecutionStatus, Sentiment


class ExecutionRun(Base):
    """프롬프트 x LLM 프로바이더 x 반복 실행 단위. 동일 프롬프트를 여러 번 실행하므로 주간 집계
    (weekly_snapshot)와 분리한다."""

    __tablename__ = "execution_run"
    __table_args__ = (
        # 배치 재실행 시 중복 저장을 막는 멱등성 키.
        UniqueConstraint(
            "batch_id",
            "prompt_id",
            "llm_provider_id",
            "repeat_index",
            name="uq_execution_run_batch_prompt_provider_repeat",
        ),
        CheckConstraint("repeat_index >= 0", name="ck_execution_run_repeat_index_non_negative"),
        # 프롬프트 상세 조회가 "이 프롬프트의 이번 주 실행들"을 찾는 패턴 — 기존 유니크 인덱스는
        # batch_id가 선행 컬럼이라 prompt_id 우선 조회에는 덜 적합하다.
        Index("ix_execution_run_prompt_batch", "prompt_id", "batch_id"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    # 주간 배치 식별자, 예: "2026-W28"
    batch_id: Mapped[str] = mapped_column(String(50), nullable=False, index=True)
    executed_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    prompt_id: Mapped[int] = mapped_column(ForeignKey("prompt.id"), nullable=False, index=True)
    llm_provider_id: Mapped[int] = mapped_column(
        ForeignKey("llm_provider.id"), nullable=False, index=True
    )
    # 0-based. REPEAT_COUNT=3이면 0,1,2.
    repeat_index: Mapped[int] = mapped_column(Integer, nullable=False)
    raw_response: Mapped[str | None] = mapped_column(Text, nullable=True)
    status: Mapped[ExecutionStatus] = mapped_column(
        Enum(ExecutionStatus, name="execution_status"),
        nullable=False,
        default=ExecutionStatus.PENDING,
    )
    error_message: Mapped[str | None] = mapped_column(Text, nullable=True)
    input_tokens: Mapped[int | None] = mapped_column(Integer, nullable=True)
    output_tokens: Mapped[int | None] = mapped_column(Integer, nullable=True)
    cost_usd: Mapped[Decimal | None] = mapped_column(Numeric(10, 6), nullable=True)

    prompt: Mapped[Prompt] = relationship()  # noqa: F821
    llm_provider: Mapped[LLMProvider] = relationship()  # noqa: F821
    mentions: Mapped[list[Mention]] = relationship(
        back_populates="execution_run", cascade="all, delete-orphan"
    )
    citations: Mapped[list[Citation]] = relationship(
        back_populates="execution_run", cascade="all, delete-orphan"
    )


class Mention(Base):
    """execution_run 응답 안에서 특정 브랜드가 언급된 기록.

    row가 존재한다는 것 자체가 언급되었다는 뜻이므로 mention_order는 NOT NULL이다
    (docs/metrics.md 참조: null은 weekly_snapshot.avg_rank 등 '집계' 단계에서 미언급을 의미한다).
    브랜드당 하나의 대표 등장 순서만 기록한다(최초 등장 기준).
    """

    __tablename__ = "mention"
    __table_args__ = (
        UniqueConstraint("execution_run_id", "brand_id", name="uq_mention_execution_run_brand"),
        CheckConstraint("mention_order >= 1", name="ck_mention_mention_order_positive"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    execution_run_id: Mapped[int] = mapped_column(
        ForeignKey("execution_run.id", ondelete="CASCADE"), nullable=False, index=True
    )
    brand_id: Mapped[int] = mapped_column(ForeignKey("brand.id"), nullable=False, index=True)
    # 답변 텍스트 내 등장 순서 (1부터). rank의 근사치일 뿐 진짜 추천 순위가 아니다.
    # docs/metrics.md 참조.
    mention_order: Mapped[int] = mapped_column(Integer, nullable=False)
    sentiment: Mapped[Sentiment] = mapped_column(
        Enum(Sentiment, name="mention_sentiment"), nullable=False
    )
    sentiment_evidence: Mapped[str | None] = mapped_column(Text, nullable=True)

    execution_run: Mapped[ExecutionRun] = relationship(back_populates="mentions")
    brand: Mapped[Brand] = relationship()  # noqa: F821


class Citation(Base):
    """execution_run 응답에 포함된 인용 URL. matched_brand_id는 brand_domain과 매칭되지 않으면
    (외부 매체 등) null이다."""

    __tablename__ = "citation"

    id: Mapped[int] = mapped_column(primary_key=True)
    execution_run_id: Mapped[int] = mapped_column(
        ForeignKey("execution_run.id", ondelete="CASCADE"), nullable=False, index=True
    )
    url: Mapped[str] = mapped_column(Text, nullable=False)
    domain: Mapped[str] = mapped_column(String(255), nullable=False, index=True)
    matched_brand_id: Mapped[int | None] = mapped_column(
        ForeignKey("brand.id"), nullable=True, index=True
    )

    execution_run: Mapped[ExecutionRun] = relationship(back_populates="citations")
    matched_brand: Mapped[Brand | None] = relationship()  # noqa: F821
