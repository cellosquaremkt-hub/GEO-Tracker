"""주간 실측 데이터 조회 — mention(브랜드 언급) 단위 1행.

fetch_mention_rows()가 쿼리를 소유하고, CSV 내보내기(build_mention_csv)와 JSON 벌크 조회
엔드포인트(app/api/mentions.py)가 이를 공유한다 — 두 곳이 각자 쿼리를 짜면 필터 조건(예:
ExecutionStatus.SUCCESS만 포함)이 어긋날 위험이 있다.
"""

from __future__ import annotations

import csv
import io
from dataclasses import dataclass

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models.brand import Brand
from app.models.enums import (
    BrandType,
    ExecutionStatus,
    FunnelIntent,
    PromptPhrasing,
    PromptSource,
    Sentiment,
    Target,
)
from app.models.execution import ExecutionRun, Mention
from app.models.llm_provider import LLMProvider
from app.models.prompt import Prompt

_HEADER = [
    "week_label",
    "prompt_id",
    "prompt_intent",
    "prompt_text",
    "industry",
    "service_line",
    "trade_lane",
    "target",
    "funnel_intent",
    "brand_type",
    "phrasing",
    "topic_group",
    "prompt_source",
    "llm_provider",
    "repeat_index",
    "brand_id",
    "brand_name",
    "is_own",
    "mention_order",
    "sentiment",
    "sentiment_evidence",
    "execution_run_id",
]


@dataclass(frozen=True)
class MentionRow:
    prompt_id: int
    prompt_intent: str
    prompt_text: str
    industry: str | None
    service_line: str | None
    trade_lane: str | None
    target: Target
    funnel_intent: FunnelIntent | None
    brand_type: BrandType | None
    phrasing: PromptPhrasing | None
    topic_group: str | None
    prompt_source: PromptSource
    llm_provider_name: str
    repeat_index: int
    brand_id: int
    brand_name: str
    is_own: bool
    mention_order: int
    sentiment: Sentiment
    sentiment_evidence: str | None
    execution_run_id: int


def fetch_mention_rows(session: Session, week: str) -> list[MentionRow]:
    rows = session.execute(
        select(
            Prompt.id,
            Prompt.intent,
            Prompt.text,
            Prompt.industry,
            Prompt.service_line,
            Prompt.trade_lane,
            Prompt.target,
            Prompt.funnel_intent,
            Prompt.brand_type,
            Prompt.phrasing,
            Prompt.topic_group,
            Prompt.source,
            LLMProvider.name,
            ExecutionRun.repeat_index,
            Brand.id,
            Brand.name,
            Brand.is_own,
            Mention.mention_order,
            Mention.sentiment,
            Mention.sentiment_evidence,
            ExecutionRun.id,
        )
        .select_from(Mention)
        .join(ExecutionRun, ExecutionRun.id == Mention.execution_run_id)
        .join(Prompt, Prompt.id == ExecutionRun.prompt_id)
        .join(LLMProvider, LLMProvider.id == ExecutionRun.llm_provider_id)
        .join(Brand, Brand.id == Mention.brand_id)
        .where(ExecutionRun.batch_id == week, ExecutionRun.status == ExecutionStatus.SUCCESS)
        .order_by(Prompt.id, LLMProvider.name, ExecutionRun.repeat_index, Mention.mention_order)
    ).all()

    return [
        MentionRow(
            prompt_id=prompt_id,
            prompt_intent=intent,
            prompt_text=text,
            industry=industry,
            service_line=service_line,
            trade_lane=trade_lane,
            target=target,
            funnel_intent=funnel_intent,
            brand_type=brand_type,
            phrasing=phrasing,
            topic_group=topic_group,
            prompt_source=prompt_source,
            llm_provider_name=provider_name,
            repeat_index=repeat_index,
            brand_id=brand_id,
            brand_name=brand_name,
            is_own=is_own,
            mention_order=mention_order,
            sentiment=sentiment,
            sentiment_evidence=evidence,
            execution_run_id=execution_run_id,
        )
        for (
            prompt_id,
            intent,
            text,
            industry,
            service_line,
            trade_lane,
            target,
            funnel_intent,
            brand_type,
            phrasing,
            topic_group,
            prompt_source,
            provider_name,
            repeat_index,
            brand_id,
            brand_name,
            is_own,
            mention_order,
            sentiment,
            evidence,
            execution_run_id,
        ) in rows
    ]


def build_mention_csv(session: Session, week: str) -> str:
    mention_rows = fetch_mention_rows(session, week)

    buffer = io.StringIO()
    writer = csv.writer(buffer)
    writer.writerow(_HEADER)
    for row in mention_rows:
        writer.writerow(
            [
                week,
                row.prompt_id,
                row.prompt_intent,
                row.prompt_text,
                row.industry or "",
                row.service_line or "",
                row.trade_lane or "",
                row.target.value,
                row.funnel_intent.value if row.funnel_intent else "",
                row.brand_type.value if row.brand_type else "",
                row.phrasing.value if row.phrasing else "",
                row.topic_group or "",
                row.prompt_source.value,
                row.llm_provider_name,
                row.repeat_index,
                row.brand_id,
                row.brand_name,
                row.is_own,
                row.mention_order,
                row.sentiment.value,
                row.sentiment_evidence or "",
                row.execution_run_id,
            ]
        )
    return buffer.getvalue()
