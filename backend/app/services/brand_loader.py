"""Brand+BrandAlias+BrandDomain을 response_parser.BrandInfo(순수 데이터)로 변환해 로드한다.

DB 접근이 필요한 얇은 어댑터 계층 — response_parser.py 자체는 SQLAlchemy를 모른다.
"""

from __future__ import annotations

from sqlalchemy import select
from sqlalchemy.orm import Session, selectinload

from app.models.brand import Brand
from app.services.response_parser import BrandInfo


def load_brand_infos(session: Session) -> list[BrandInfo]:
    result = session.execute(
        select(Brand).options(selectinload(Brand.aliases), selectinload(Brand.domains))
    )
    brands = result.scalars().all()
    return [
        BrandInfo(
            id=b.id,
            name=b.name,
            aliases=tuple(a.alias_text for a in b.aliases),
            domains=tuple(d.domain for d in b.domains),
        )
        for b in brands
    ]
