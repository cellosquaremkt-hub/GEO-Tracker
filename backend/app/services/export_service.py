"""주간 실측 데이터 CSV 내보내기 — mention(브랜드 언급) 단위 1행."""

from __future__ import annotations

import csv
import io

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models.brand import Brand
from app.models.enums import ExecutionStatus
from app.models.execution import ExecutionRun, Mention
from app.models.llm_provider import LLMProvider
from app.models.prompt import Prompt

_HEADER = [
    "week_label",
    "prompt_id",
    "prompt_intent",
    "prompt_text",
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


def build_mention_csv(session: Session, week: str) -> str:
    rows = session.execute(
        select(
            Prompt.id,
            Prompt.intent,
            Prompt.text,
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

    buffer = io.StringIO()
    writer = csv.writer(buffer)
    writer.writerow(_HEADER)
    for (
        prompt_id,
        intent,
        text,
        provider_name,
        repeat_index,
        brand_id,
        brand_name,
        is_own,
        mention_order,
        sentiment,
        evidence,
        execution_run_id,
    ) in rows:
        writer.writerow(
            [
                week,
                prompt_id,
                intent,
                text,
                provider_name,
                repeat_index,
                brand_id,
                brand_name,
                is_own,
                mention_order,
                sentiment.value,
                evidence or "",
                execution_run_id,
            ]
        )
    return buffer.getvalue()
