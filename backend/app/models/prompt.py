from __future__ import annotations

from datetime import datetime

from sqlalchemy import Boolean, DateTime, Enum, ForeignKey, Integer, String, Text
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base
from app.models.enums import (
    BrandType,
    FunnelIntent,
    Language,
    Priority,
    PromptPhrasing,
    PromptSource,
    Target,
)


class Prompt(Base):
    """프롬프트 텍스트는 불변이다 (CLAUDE.md). 문구 수정이 필요하면 is_active=False로 비활성화하고
    supersedes_id로 이전 버전을 가리키는 새 row(version+1)를 만든다.

    industry/service_line/trade_lane은 자유 텍스트다 — 값 종류가 계속 늘어나는 개방형
    분류라(2026-07-28 기준 산업만 27종) enum으로 고정하면 새 카테고리가 생길 때마다
    마이그레이션이 필요해진다. funnel_intent/brand_type/phrasing은 값이 고정된 소수
    집합이라 enum으로 관리한다.
    엑셀 피벗 등 다차원 조회는 export_service.py의 CSV(각 컬럼이 그대로 열이 됨)로 지원한다 —
    앱 안에 별도 피벗 UI를 만들지 않는 이유는 docs/backlog.md 참조.
    """

    __tablename__ = "prompt"

    id: Mapped[int] = mapped_column(primary_key=True)
    text: Mapped[str] = mapped_column(Text, nullable=False)
    intent: Mapped[str] = mapped_column(String(100), nullable=False)
    target: Mapped[Target] = mapped_column(Enum(Target, name="prompt_target"), nullable=False)
    priority: Mapped[Priority] = mapped_column(
        Enum(Priority, name="prompt_priority"), nullable=False
    )
    language: Mapped[Language] = mapped_column(
        Enum(Language, name="prompt_language"), nullable=False
    )
    is_active: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    version: Mapped[int] = mapped_column(Integer, nullable=False, default=1)
    supersedes_id: Mapped[int | None] = mapped_column(
        ForeignKey("prompt.id"), nullable=True, index=True
    )

    industry: Mapped[str | None] = mapped_column(String(100), nullable=True)
    service_line: Mapped[str | None] = mapped_column(String(100), nullable=True)
    trade_lane: Mapped[str | None] = mapped_column(String(100), nullable=True)
    funnel_intent: Mapped[FunnelIntent | None] = mapped_column(
        Enum(FunnelIntent, name="prompt_funnel_intent"), nullable=True
    )
    brand_type: Mapped[BrandType | None] = mapped_column(
        Enum(BrandType, name="prompt_brand_type"), nullable=True, index=True
    )
    phrasing: Mapped[PromptPhrasing | None] = mapped_column(
        Enum(PromptPhrasing, name="prompt_phrasing"), nullable=True
    )
    # 같은 원본 행(엑셀 등)에서 나온 V1/V2 등 문구 변형 쌍을 묶는 키 — "{source_file}:{row_number}".
    topic_group: Mapped[str | None] = mapped_column(String(150), nullable=True, index=True)

    source: Mapped[PromptSource] = mapped_column(
        Enum(PromptSource, name="prompt_source"), nullable=False, default=PromptSource.MANUAL
    )
    source_file: Mapped[str | None] = mapped_column(String(255), nullable=True)
    imported_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    supersedes: Mapped[Prompt | None] = relationship(
        back_populates="superseded_by", remote_side="[Prompt.id]"
    )
    superseded_by: Mapped[list[Prompt]] = relationship(back_populates="supersedes")
