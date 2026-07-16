from __future__ import annotations

from decimal import Decimal

from pydantic import BaseModel, ConfigDict


class TrendPointResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    week: str
    sov: Decimal | None


class BrandTrendResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    brand_id: int
    brand_name: str
    points: list[TrendPointResponse]


class TrendsResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    weeks: list[str]
    series: list[BrandTrendResponse]
