from __future__ import annotations

from decimal import Decimal

from pydantic import BaseModel, ConfigDict

from app.models.enums import Priority


class WeeklyReportSummaryResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    week: str
    total_execution_runs: int
    success_count: int
    failed_count: int
    own_total_sov: Decimal


class VulnerablePromptResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    prompt_id: int
    prompt_text: str
    intent: str
    priority: Priority
    reason: str


class CompetitorAdvantagePromptResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    prompt_id: int
    prompt_text: str
    own_avg_rank: Decimal | None
    leading_competitor_id: int
    leading_competitor_name: str
    leading_competitor_avg_rank: Decimal


class WeeklyReportResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    summary: WeeklyReportSummaryResponse
    vulnerable_prompts: list[VulnerablePromptResponse]
    competitor_advantage_prompts: list[CompetitorAdvantagePromptResponse]
