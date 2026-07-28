from __future__ import annotations

from pydantic import BaseModel, ConfigDict

from app.models.enums import Sentiment


class MentionRowResponse(BaseModel):
    """GET /mentions 1행 — 프롬프트별 개별 조회(N+1) 대신 주간 전체를 한 번에 내려주는 벌크 응답.

    export_service.MentionRow가 CSV 내보내기용으로 더 많은 프롬프트 메타데이터(industry 등)를
    갖고 있지만, 여기서는 프론트 화면(대시보드 Top keywords/리포트 감정 분석)이 실제로 쓰는
    필드만 노출한다 — from_attributes=True라 MentionRow를 그대로 검증에 넘겨도 나머지 필드는
    무시된다.
    """

    model_config = ConfigDict(from_attributes=True)

    prompt_id: int
    prompt_text: str
    prompt_intent: str
    llm_provider_name: str
    execution_run_id: int
    brand_id: int
    brand_name: str
    mention_order: int
    sentiment: Sentiment
    sentiment_evidence: str | None
