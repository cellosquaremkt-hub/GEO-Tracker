from __future__ import annotations

from datetime import datetime

from sqlalchemy import Boolean, DateTime, ForeignKey, String, UniqueConstraint, func
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base


class Brand(Base):
    """CLAUDE.md 핵심 도메인 규칙: 브랜드는 고유 ID로만 참조하고, 순서 인덱스로 매핑하지 않는다."""

    __tablename__ = "brand"

    id: Mapped[int] = mapped_column(primary_key=True)
    name: Mapped[str] = mapped_column(String(255), nullable=False, unique=True)
    is_own: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )

    aliases: Mapped[list[BrandAlias]] = relationship(
        back_populates="brand", cascade="all, delete-orphan"
    )
    domains: Mapped[list[BrandDomain]] = relationship(
        back_populates="brand", cascade="all, delete-orphan"
    )


class BrandAlias(Base):
    """한/영 혼용 표기 등 브랜드 별칭. 언급 텍스트 매칭에 사용한다.

    예: "Kuehne+Nagel", "K+N", "퀴네나겔".
    """

    __tablename__ = "brand_alias"
    __table_args__ = (
        UniqueConstraint("brand_id", "alias_text", name="uq_brand_alias_brand_id_alias_text"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    brand_id: Mapped[int] = mapped_column(
        ForeignKey("brand.id", ondelete="CASCADE"), nullable=False, index=True
    )
    alias_text: Mapped[str] = mapped_column(String(255), nullable=False)

    brand: Mapped[Brand] = relationship(back_populates="aliases")


class BrandDomain(Base):
    """인용 URL의 도메인을 브랜드에 매칭하기 위한 테이블."""

    __tablename__ = "brand_domain"

    id: Mapped[int] = mapped_column(primary_key=True)
    brand_id: Mapped[int] = mapped_column(
        ForeignKey("brand.id", ondelete="CASCADE"), nullable=False, index=True
    )
    # 도메인은 브랜드 간에 겹칠 수 없으므로 전역 유니크로 둔다 (인용 매칭이 1:1이어야 함).
    domain: Mapped[str] = mapped_column(String(255), nullable=False, unique=True)

    brand: Mapped[Brand] = relationship(back_populates="domains")
