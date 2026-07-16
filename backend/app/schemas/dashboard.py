from __future__ import annotations

from decimal import Decimal

from pydantic import BaseModel, ConfigDict


class DashboardSummaryResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    week: str
    previous_week: str
    total_sov: Decimal
    rank: int
    total_ranked_entities: int
    sov_delta: Decimal | None
    negative_mention_count: int
