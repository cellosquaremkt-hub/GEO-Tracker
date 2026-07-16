from __future__ import annotations

from pydantic import BaseModel, Field


class BatchConfigResponse(BaseModel):
    repeat_count: int


class BatchConfigUpdateRequest(BaseModel):
    repeat_count: int = Field(ge=1, le=20)
