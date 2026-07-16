"""관리용 엔드포인트 보호 — ADMIN_API_KEY 헤더 인증 (CLAUDE.md 참조).

FastAPI의 Depends() 기반 의존성 대신 Flask 라우트 함수를 감싸는 데코레이터로 재작성했다.
"""

from __future__ import annotations

from collections.abc import Callable
from functools import wraps
from typing import Any, TypeVar

from flask import make_response, request

from app.core.config import settings

F = TypeVar("F", bound=Callable[..., Any])


def require_admin_api_key(view_func: F) -> F:
    @wraps(view_func)
    def wrapper(*args: Any, **kwargs: Any) -> Any:
        provided = request.headers.get("X-Admin-Api-Key")
        if not provided or provided != settings.admin_api_key:
            return make_response(
                {"detail": "X-Admin-Api-Key 헤더가 없거나 올바르지 않습니다."}, 401
            )
        return view_func(*args, **kwargs)

    return wrapper  # type: ignore[return-value]
