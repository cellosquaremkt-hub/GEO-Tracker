from __future__ import annotations

from flask import Blueprint, jsonify, request

from app.core.security import require_admin_api_key
from app.db.session import get_session
from app.schemas.brands import (
    BrandCreateRequest,
    BrandDetailResponse,
    BrandOverviewResponse,
    BrandUpdateRequest,
)
from app.services.brand_service import (
    BrandConflictError,
    create_brand,
    get_brand,
    get_brand_overview,
    list_brands,
    update_brand,
)
from app.services.week_utils import compute_current_week_label

bp = Blueprint("brands", __name__, url_prefix="/brands")


@bp.get("/<int:brand_id>/overview")
def get_brand_overview_endpoint(brand_id: int):
    week_label = request.args.get("week") or compute_current_week_label()
    session = get_session()
    overview = get_brand_overview(session, brand_id, week_label)
    if overview is None:
        return jsonify({"detail": f"brand_id {brand_id}를 찾을 수 없습니다."}), 404
    return jsonify(BrandOverviewResponse.model_validate(overview).model_dump(mode="json"))


# --- 관리자 전용 (ADMIN_API_KEY 필요) ---------------------------------------------------


@bp.get("")
@require_admin_api_key
def list_brands_endpoint():
    session = get_session()
    brands = list_brands(session)
    return jsonify([BrandDetailResponse.model_validate(b).model_dump(mode="json") for b in brands])


@bp.get("/<int:brand_id>")
@require_admin_api_key
def get_brand_endpoint(brand_id: int):
    session = get_session()
    brand = get_brand(session, brand_id)
    if brand is None:
        return jsonify({"detail": f"brand_id {brand_id}를 찾을 수 없습니다."}), 404
    return jsonify(BrandDetailResponse.model_validate(brand).model_dump(mode="json"))


@bp.post("")
@require_admin_api_key
def create_brand_endpoint():
    payload = BrandCreateRequest.model_validate(request.get_json(force=True))
    session = get_session()
    try:
        brand = create_brand(
            session,
            name=payload.name,
            is_own=payload.is_own,
            aliases=payload.aliases,
            domains=payload.domains,
        )
    except BrandConflictError as exc:
        return jsonify({"detail": str(exc)}), 409
    return jsonify(BrandDetailResponse.model_validate(brand).model_dump(mode="json")), 201


@bp.put("/<int:brand_id>")
@require_admin_api_key
def update_brand_endpoint(brand_id: int):
    payload = BrandUpdateRequest.model_validate(request.get_json(force=True))
    session = get_session()
    try:
        brand = update_brand(
            session,
            brand_id,
            name=payload.name,
            is_own=payload.is_own,
            aliases=payload.aliases,
            domains=payload.domains,
        )
    except BrandConflictError as exc:
        return jsonify({"detail": str(exc)}), 409
    if brand is None:
        return jsonify({"detail": f"brand_id {brand_id}를 찾을 수 없습니다."}), 404
    return jsonify(BrandDetailResponse.model_validate(brand).model_dump(mode="json"))
