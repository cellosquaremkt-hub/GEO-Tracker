from __future__ import annotations

from pydantic import BaseModel, ConfigDict


class LLMProviderResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    name: str
    model_string: str
    supports_web_search: bool
    is_active: bool


class LLMProviderUpdateRequest(BaseModel):
    model_string: str | None = None
    supports_web_search: bool | None = None
    is_active: bool | None = None
