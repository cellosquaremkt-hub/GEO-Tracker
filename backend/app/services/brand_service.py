"""브랜드 조회/관리 서비스.

get_brand_overview()는 공개 조회 엔드포인트용. list_brands/get_brand/create_brand/update_brand는
관리자 CRUD용 — 브랜드는 항상 고유 ID로만 참조하고(CLAUDE.md), 별칭/도메인은 brand_alias/
brand_domain 전체 교체 방식으로 관리한다(PUT 시맨틱: 값이 주어지면 전체 대체).
"""

from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal

from sqlalchemy import delete, func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session, selectinload

from app.models.brand import Brand, BrandAlias, BrandDomain
from app.models.enums import ExecutionStatus
from app.models.execution import Citation, ExecutionRun, Mention
from app.models.llm_provider import LLMProvider
from app.models.snapshot import WeeklySnapshot


class BrandConflictError(Exception):
    """브랜드 이름 또는 도메인이 이미 존재해 유니크 제약을 위반할 때."""


@dataclass(frozen=True)
class ProviderOverview:
    llm_provider_id: int
    llm_provider_name: str
    sov: Decimal | None
    mention_count: int
    cited_pages: list[str]


@dataclass(frozen=True)
class BrandOverview:
    brand_id: int
    brand_name: str
    week: str
    providers: list[ProviderOverview]


def get_brand_overview(session: Session, brand_id: int, week: str) -> BrandOverview | None:
    brand = session.get(Brand, brand_id)
    if brand is None:
        return None

    providers = (
        session.execute(select(LLMProvider).where(LLMProvider.is_active.is_(True))).scalars().all()
    )

    snapshot_by_provider: dict[int, Decimal] = dict(
        session.execute(
            select(WeeklySnapshot.llm_provider_id, WeeklySnapshot.sov).where(
                WeeklySnapshot.week_label == week,
                WeeklySnapshot.brand_id == brand_id,
                WeeklySnapshot.llm_provider_id.is_not(None),
            )
        ).all()
    )

    provider_overviews: list[ProviderOverview] = []
    for provider in providers:
        run_scope_subq = (
            select(ExecutionRun.id)
            .where(
                ExecutionRun.batch_id == week,
                ExecutionRun.status == ExecutionStatus.SUCCESS,
                ExecutionRun.llm_provider_id == provider.id,
            )
            .subquery()
        )
        run_ids = select(run_scope_subq.c.id)

        mention_count = session.execute(
            select(func.count())
            .select_from(Mention)
            .where(Mention.brand_id == brand_id, Mention.execution_run_id.in_(run_ids))
        ).scalar_one()

        cited_pages = list(
            session.execute(
                select(Citation.url.distinct()).where(
                    Citation.matched_brand_id == brand_id,
                    Citation.execution_run_id.in_(run_ids),
                )
            )
            .scalars()
            .all()
        )

        provider_overviews.append(
            ProviderOverview(
                llm_provider_id=provider.id,
                llm_provider_name=provider.name,
                sov=snapshot_by_provider.get(provider.id),
                mention_count=mention_count,
                cited_pages=cited_pages,
            )
        )

    return BrandOverview(
        brand_id=brand.id, brand_name=brand.name, week=week, providers=provider_overviews
    )


def _brand_query():
    return select(Brand).options(selectinload(Brand.aliases), selectinload(Brand.domains))


def list_brands(session: Session) -> list[Brand]:
    result = session.execute(_brand_query().order_by(Brand.id))
    return list(result.scalars().all())


def get_brand(session: Session, brand_id: int) -> Brand | None:
    result = session.execute(_brand_query().where(Brand.id == brand_id))
    return result.scalar_one_or_none()


def create_brand(
    session: Session,
    *,
    name: str,
    is_own: bool,
    aliases: list[str],
    domains: list[str],
) -> Brand:
    brand = Brand(name=name, is_own=is_own)
    try:
        session.add(brand)
        session.flush()
        for alias_text in aliases:
            session.add(BrandAlias(brand_id=brand.id, alias_text=alias_text))
        for domain in domains:
            session.add(BrandDomain(brand_id=brand.id, domain=domain))
        session.commit()
    except IntegrityError as exc:
        session.rollback()
        raise BrandConflictError(str(exc.orig)) from exc

    created = get_brand(session, brand.id)
    assert created is not None  # 방금 커밋했으므로 항상 존재한다.
    return created


def update_brand(
    session: Session,
    brand_id: int,
    *,
    name: str | None = None,
    is_own: bool | None = None,
    aliases: list[str] | None = None,
    domains: list[str] | None = None,
) -> Brand | None:
    brand = session.get(Brand, brand_id)
    if brand is None:
        return None

    if name is not None:
        brand.name = name
    if is_own is not None:
        brand.is_own = is_own
    if aliases is not None:
        session.execute(delete(BrandAlias).where(BrandAlias.brand_id == brand_id))
        for alias_text in aliases:
            session.add(BrandAlias(brand_id=brand_id, alias_text=alias_text))
    if domains is not None:
        session.execute(delete(BrandDomain).where(BrandDomain.brand_id == brand_id))
        for domain in domains:
            session.add(BrandDomain(brand_id=brand_id, domain=domain))

    try:
        session.commit()
    except IntegrityError as exc:
        session.rollback()
        raise BrandConflictError(str(exc.orig)) from exc

    return get_brand(session, brand_id)
