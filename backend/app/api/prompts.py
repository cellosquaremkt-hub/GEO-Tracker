from __future__ import annotations

from flask import Blueprint, jsonify, request

from app.core.security import require_admin_api_key
from app.db.session import get_session
from app.models.enums import BrandType, Language, Priority, PromptSource, Target
from app.schemas.prompts import (
    PromptCreateRequest,
    PromptDetailResponse,
    PromptImportResultResponse,
    PromptResponse,
)
from app.services.prompt_import_service import PromptImportError, import_prompts_from_excel
from app.services.prompt_service import (
    PromptNotFoundError,
    create_prompt,
    deactivate_all_active,
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
        brand_type=BrandType(args["brand_type"]) if args.get("brand_type") else None,
        source=PromptSource(args["source"]) if args.get("source") else None,
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


@bp.post("/deactivate-all")
@require_admin_api_key
def deactivate_all_active_endpoint():
    """현재 활성 프롬프트를 전부 비활성화한다 — 프롬프트 세트를 통째로 교체할 때 쓴다
    (텍스트/실행 이력은 그대로 남고 is_active만 꺼진다)."""
    session = get_session()
    count = deactivate_all_active(session)
    return jsonify({"deactivated_count": count})


@bp.post("/import-excel")
@require_admin_api_key
def import_prompts_excel_endpoint():
    """엑셀 업로드로 프롬프트를 대량 등록한다 (multipart/form-data, 필드명 'file').

    기대 스키마는 app/services/prompt_import_service.py의 _EXPECTED_HEADER 참조. 한 행에서
    V1(검색어형)/V2(질문형) 두 프롬프트가 만들어지고 전부 source=EXCEL_IMPORT로 표시된다.
    """
    file = request.files.get("file")
    if file is None or not file.filename:
        return jsonify({"detail": "'file' 필드에 엑셀 파일을 첨부해야 합니다."}), 400

    session = get_session()
    try:
        result = import_prompts_from_excel(session, file.read(), file.filename)
    except PromptImportError as exc:
        return jsonify(
            {
                "detail": str(exc),
                "row_errors": [
                    {"row_number": e.row_number, "message": e.message} for e in exc.row_errors
                ],
            }
        ), 400
    return jsonify(PromptImportResultResponse.model_validate(result).model_dump(mode="json")), 201
