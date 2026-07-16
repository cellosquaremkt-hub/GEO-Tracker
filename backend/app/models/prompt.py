from __future__ import annotations

from sqlalchemy import Boolean, Enum, ForeignKey, Integer, String, Text
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base
from app.models.enums import Language, Priority, Target


class Prompt(Base):
    """프롬프트 텍스트는 불변이다 (CLAUDE.md). 문구 수정이 필요하면 is_active=False로 비활성화하고
    supersedes_id로 이전 버전을 가리키는 새 row(version+1)를 만든다."""

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

    supersedes: Mapped[Prompt | None] = relationship(
        back_populates="superseded_by", remote_side="[Prompt.id]"
    )
    superseded_by: Mapped[list[Prompt]] = relationship(back_populates="supersedes")
