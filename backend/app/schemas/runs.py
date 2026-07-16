from __future__ import annotations

from decimal import Decimal

from pydantic import BaseModel, ConfigDict


class BatchStatusResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    batch_id: str
    pending: int
    running: int
    success: int
    failed: int
    total_cost_usd: Decimal
