from __future__ import annotations

from decimal import Decimal

from pydantic import BaseModel, ConfigDict, Field


class ProviderOverviewResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    llm_provider_id: int
    llm_provider_name: str
    sov: Decimal | None
    mention_count: int
    cited_pages: list[str]


class BrandOverviewResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    brand_id: int
    brand_name: str
    week: str
    providers: list[ProviderOverviewResponse]


class BrandAliasResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    alias_text: str


class BrandDomainResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    domain: str


class BrandDetailResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    name: str
    is_own: bool
    aliases: list[BrandAliasResponse]
    domains: list[BrandDomainResponse]


class BrandCreateRequest(BaseModel):
    name: str
    is_own: bool = False
    aliases: list[str] = Field(default_factory=list)
    domains: list[str] = Field(default_factory=list)


class BrandUpdateRequest(BaseModel):
    name: str | None = None
    is_own: bool | None = None
    # None = 변경 안 함, [] = 전부 삭제, [...] = 전체 교체.
    aliases: list[str] | None = None
    domains: list[str] | None = None
