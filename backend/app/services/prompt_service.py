"""프롬프트 목록/상세 조회 + 관리자 CRUD.

get_prompt_detail()은 mention_order만 저장하는 Mention 테이블 설계(오프셋 미저장) 때문에,
하이라이트용 문자 오프셋을 요청 시점에 brand_matching으로 다시 계산한다.

CLAUDE.md 핵심 도메인 규칙: 프롬프트 텍스트는 불변이다. create_prompt()만 있고 "텍스트 수정"
API는 없다 — 문구를 바꾸려면 새 버전을 만들고(supersedes_id로 이전 버전과 연결) 이전 버전은
deactivate_prompt()로 비활성화한다. 두 동작은 독립적이라 admin이 명시적으로 둘 다 호출해야
한다(신규 생성이 이전 버전을 자동으로 비활성화하지 않는다).
"""

from __future__ import annotations

from dataclasses import dataclass

from sqlalchemy import select
from sqlalchemy.orm import Session, selectinload

from app.models.enums import ExecutionStatus, Language, Priority, Sentiment, Target
from app.models.execution import Citation, ExecutionRun, Mention
from app.models.prompt import Prompt
from app.services.brand_loader import load_brand_infos
from app.services.brand_matching import find_all_alias_matches


class PromptNotFoundError(Exception):
    """create_prompt()에 존재하지 않는 supersedes_id가 주어졌을 때."""


def list_prompts(
    session: Session,
    *,
    intent: str | None = None,
    target: Target | None = None,
    priority: Priority | None = None,
    language: Language | None = None,
    is_active: bool | None = None,
) -> list[Prompt]:
    stmt = select(Prompt)
    if intent is not None:
        stmt = stmt.where(Prompt.intent == intent)
    if target is not None:
        stmt = stmt.where(Prompt.target == target)
    if priority is not None:
        stmt = stmt.where(Prompt.priority == priority)
    if language is not None:
        stmt = stmt.where(Prompt.language == language)
    if is_active is not None:
        stmt = stmt.where(Prompt.is_active == is_active)
    stmt = stmt.order_by(Prompt.id)
    return list(session.execute(stmt).scalars().all())


@dataclass(frozen=True)
class MentionHighlight:
    brand_id: int
    brand_name: str
    start: int
    end: int
    matched_text: str


@dataclass(frozen=True)
class MentionDetail:
    brand_id: int
    brand_name: str
    mention_order: int
    sentiment: Sentiment
    sentiment_evidence: str | None


@dataclass(frozen=True)
class CitationDetail:
    url: str
    domain: str
    matched_brand_id: int | None
    matched_brand_name: str | None


@dataclass(frozen=True)
class ExecutionDetail:
    execution_run_id: int
    llm_provider_id: int
    llm_provider_name: str
    repeat_index: int
    status: ExecutionStatus
    raw_response: str | None
    highlights: list[MentionHighlight]
    mentions: list[MentionDetail]
    citations: list[CitationDetail]


@dataclass(frozen=True)
class PromptDetail:
    prompt_id: int
    prompt_text: str
    week: str
    executions: list[ExecutionDetail]


def get_prompt_detail(session: Session, prompt_id: int, week: str) -> PromptDetail | None:
    prompt = session.get(Prompt, prompt_id)
    if prompt is None:
        return None

    runs = (
        session.execute(
            select(ExecutionRun)
            .options(selectinload(ExecutionRun.llm_provider))
            .where(ExecutionRun.prompt_id == prompt_id, ExecutionRun.batch_id == week)
            .order_by(ExecutionRun.llm_provider_id, ExecutionRun.repeat_index)
        )
        .scalars()
        .all()
    )

    brands = load_brand_infos(session)
    brand_names = {b.id: b.name for b in brands}
    matching_brands = [b.as_matching() for b in brands]

    executions: list[ExecutionDetail] = []
    for run in runs:
        highlights: list[MentionHighlight] = []
        if run.raw_response:
            highlights = [
                MentionHighlight(
                    brand_id=m.brand_id,
                    brand_name=brand_names.get(m.brand_id, str(m.brand_id)),
                    start=m.start,
                    end=m.end,
                    matched_text=m.matched_text,
                )
                for m in find_all_alias_matches(run.raw_response, matching_brands)
            ]

        mention_rows = (
            session.execute(select(Mention).where(Mention.execution_run_id == run.id))
            .scalars()
            .all()
        )
        mentions = [
            MentionDetail(
                brand_id=m.brand_id,
                brand_name=brand_names.get(m.brand_id, str(m.brand_id)),
                mention_order=m.mention_order,
                sentiment=m.sentiment,
                sentiment_evidence=m.sentiment_evidence,
            )
            for m in mention_rows
        ]

        citation_rows = (
            session.execute(select(Citation).where(Citation.execution_run_id == run.id))
            .scalars()
            .all()
        )
        citations = [
            CitationDetail(
                url=c.url,
                domain=c.domain,
                matched_brand_id=c.matched_brand_id,
                matched_brand_name=(
                    brand_names.get(c.matched_brand_id) if c.matched_brand_id is not None else None
                ),
            )
            for c in citation_rows
        ]

        executions.append(
            ExecutionDetail(
                execution_run_id=run.id,
                llm_provider_id=run.llm_provider_id,
                llm_provider_name=run.llm_provider.name,
                repeat_index=run.repeat_index,
                status=run.status,
                raw_response=run.raw_response,
                highlights=highlights,
                mentions=mentions,
                citations=citations,
            )
        )

    return PromptDetail(
        prompt_id=prompt.id, prompt_text=prompt.text, week=week, executions=executions
    )


def create_prompt(
    session: Session,
    *,
    text: str,
    intent: str,
    target: Target,
    priority: Priority,
    language: Language,
    supersedes_id: int | None = None,
) -> Prompt:
    version = 1
    if supersedes_id is not None:
        old = session.get(Prompt, supersedes_id)
        if old is None:
            raise PromptNotFoundError(f"supersedes_id {supersedes_id}를 찾을 수 없습니다.")
        version = old.version + 1

    prompt = Prompt(
        text=text,
        intent=intent,
        target=target,
        priority=priority,
        language=language,
        version=version,
        supersedes_id=supersedes_id,
    )
    session.add(prompt)
    session.commit()
    session.refresh(prompt)
    return prompt


def deactivate_prompt(session: Session, prompt_id: int) -> Prompt | None:
    prompt = session.get(Prompt, prompt_id)
    if prompt is None:
        return None
    prompt.is_active = False
    session.commit()
    session.refresh(prompt)
    return prompt
