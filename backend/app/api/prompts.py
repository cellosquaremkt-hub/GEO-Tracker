from __future__ import annotations

from flask import Blueprint, jsonify, request

from app.core.security import require_admin_api_key
from app.db.session import get_session
from app.models.enums import Language, Priority, Target
from app.schemas.prompts import PromptCreateRequest, PromptDetailResponse, PromptResponse
from app.services.prompt_service import (
    PromptNotFoundError,
    create_prompt,
    deactivate_prompt,
    get_prompt_detail,
    list_prompts,
)
from app.services.week_utils import compute_current_week_label

bp = Blueprint("prompts", __name__, url_prefix="/prompts")


@bp.get("")
def list_prompts_endpoint():
    args = request.args
    session = get_session()
    prompts = list_prompts(
        session,
        intent=args.get("intent"),
        target=Target(args["target"]) if args.get("target") else None,
        priority=Priority(args["priority"]) if args.get("priority") else None,
        language=Language(args["language"]) if args.get("language") else None,
        is_active=(args.get("is_active").lower() == "true") if args.get("is_active") else None,
    )
    return jsonify([PromptResponse.model_validate(p).model_dump(mode="json") for p in prompts])


@bp.get("/<int:prompt_id>/detail")
def get_prompt_detail_endpoint(prompt_id: int):
    week_label = request.args.get("week") or compute_current_week_label()
    session = get_session()
    detail = get_prompt_detail(session, prompt_id, week_label)
    if detail is None:
        return jsonify({"detail": f"prompt_id {prompt_id}를 찾을 수 없습니다."}), 404
    return jsonify(PromptDetailResponse.model_validate(detail).model_dump(mode="json"))


# --- 관리자 전용 (ADMIN_API_KEY 필요) ---------------------------------------------------


@bp.post("")
@require_admin_api_key
def create_prompt_endpoint():
    payload = PromptCreateRequest.model_validate(request.get_json(force=True))
    session = get_session()
    try:
        prompt = create_prompt(
            session,
            text=payload.text,
            intent=payload.intent,
            target=payload.target,
            priority=payload.priority,
            language=payload.language,
            supersedes_id=payload.supersedes_id,
        )
    except PromptNotFoundError as exc:
        return jsonify({"detail": str(exc)}), 400
    return jsonify(PromptResponse.model_validate(prompt).model_dump(mode="json")), 201


@bp.put("/<int:prompt_id>/deactivate")
@require_admin_api_key
def deactivate_prompt_endpoint(prompt_id: int):
    session = get_session()
    prompt = deactivate_prompt(session, prompt_id)
    if prompt is None:
        return jsonify({"detail": f"prompt_id {prompt_id}를 찾을 수 없습니다."}), 404
    return jsonify(PromptResponse.model_validate(prompt).model_dump(mode="json"))
