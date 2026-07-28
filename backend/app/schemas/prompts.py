from __future__ import annotations

from pydantic import BaseModel, ConfigDict

from app.models.enums import (
    BrandType,
    ExecutionStatus,
    FunnelIntent,
    Language,
    Priority,
    PromptPhrasing,
    PromptSource,
    Sentiment,
    Target,
)


class PromptResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    text: str
    intent: str
    target: Target
    priority: Priority
    language: Language
    is_active: bool
    version: int
    supersedes_id: int | None
    industry: str | None = None
    service_line: str | None = None
    trade_lane: str | None = None
    funnel_intent: FunnelIntent | None = None
    brand_type: BrandType | None = None
    phrasing: PromptPhrasing | None = None
    topic_group: str | None = None
    source: PromptSource
    source_file: str | None = None


class PromptCreateRequest(BaseModel):
    text: str
    intent: str
    target: Target
    priority: Priority
    language: Language
    # 기존 프롬프트의 새 버전을 만드는 경우에만 지정한다. 이전 버전은 자동 비활성화되지 않는다 —
    # 별도로 PUT /prompts/{old_id}/deactivate를 호출해야 한다.
    supersedes_id: int | None = None


class PromptImportRowErrorResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    row_number: int
    message: str


class PromptImportResultResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    source_file: str
    rows_processed: int
    prompts_created: int


class MentionHighlightResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    brand_id: int
    brand_name: str
    start: int
    end: int
    matched_text: str


class MentionDetailResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    brand_id: int
    brand_name: str
    mention_order: int
    sentiment: Sentiment
    sentiment_evidence: str | None


class CitationDetailResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    url: str
    domain: str
    matched_brand_id: int | None
    matched_brand_name: str | None


class ExecutionDetailResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    execution_run_id: int
    llm_provider_id: int
    llm_provider_name: str
    repeat_index: int
    status: ExecutionStatus
    raw_response: str | None
    highlights: list[MentionHighlightResponse]
    mentions: list[MentionDetailResponse]
    citations: list[CitationDetailResponse]


class PromptDetailResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    prompt_id: int
    prompt_text: str
    week: str
    executions: list[ExecutionDetailResponse]
