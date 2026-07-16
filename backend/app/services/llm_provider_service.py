"""LLM 프로바이더 관리 — 활성/비활성 토글 및 모델 설정.

name은 수정 대상에서 뺀다 — app.llm_clients.factory.get_adapter()가 name으로 어댑터 클래스를
찾으므로, name이 바뀌면 기존 execution_run/알림 등에서 참조가 끊긴다.
"""

from __future__ import annotations

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models.llm_provider import LLMProvider


def list_llm_providers(session: Session) -> list[LLMProvider]:
    result = session.execute(select(LLMProvider).order_by(LLMProvider.id))
    return list(result.scalars().all())


def update_llm_provider(
    session: Session,
    provider_id: int,
    *,
    model_string: str | None = None,
    supports_web_search: bool | None = None,
    is_active: bool | None = None,
) -> LLMProvider | None:
    provider = session.get(LLMProvider, provider_id)
    if provider is None:
        return None

    if model_string is not None:
        provider.model_string = model_string
    if supports_web_search is not None:
        provider.supports_web_search = supports_web_search
    if is_active is not None:
        provider.is_active = is_active

    session.commit()
    session.refresh(provider)
    return provider
