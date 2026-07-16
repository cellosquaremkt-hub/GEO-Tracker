from __future__ import annotations

from flask import Blueprint, jsonify, request

from app.core.security import require_admin_api_key
from app.db.session import get_session
from app.schemas.llm_providers import LLMProviderResponse, LLMProviderUpdateRequest
from app.services.llm_provider_service import list_llm_providers, update_llm_provider

bp = Blueprint("llm_providers", __name__, url_prefix="/llm-providers")


@bp.get("")
@require_admin_api_key
def list_llm_providers_endpoint():
    session = get_session()
    providers = list_llm_providers(session)
    return jsonify(
        [LLMProviderResponse.model_validate(p).model_dump(mode="json") for p in providers]
    )


@bp.put("/<int:provider_id>")
@require_admin_api_key
def update_llm_provider_endpoint(provider_id: int):
    payload = LLMProviderUpdateRequest.model_validate(request.get_json(force=True))
    session = get_session()
    provider = update_llm_provider(
        session,
        provider_id,
        model_string=payload.model_string,
        supports_web_search=payload.supports_web_search,
        is_active=payload.is_active,
    )
    if provider is None:
        return jsonify({"detail": f"llm_provider_id {provider_id}를 찾을 수 없습니다."}), 404
    return jsonify(LLMProviderResponse.model_validate(provider).model_dump(mode="json"))
