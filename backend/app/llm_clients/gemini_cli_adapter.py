"""Gemini CLI 어댑터 — 구독 좌석 기반 측정 채널(API 키 아님).

조사 근거: docs/llm_clis.md §3 (참고 프로젝트 20260709, 2026-07-10 확인). 인증은 Gemini CLI의
캐시된 OAuth 자격증명(최초 1회 브라우저 로그인 후 로컬에 저장)을 재사용한다 —
docs/operations.md 참조.

`--output-format json`으로 구조화된 응답을 받는다. Claude Code/Codex와 달리 Gemini CLI는
기본적으로 google_web_search 도구가 항상 사용 가능한 상태이며 모델이 필요하다고 판단하면
자동으로 호출한다(별도 활성화 플래그 불필요) — 세 CLI 중 유일하게 명시적 on/off 스위치가 없다.
"""

from __future__ import annotations

import json
from typing import Any

from app.core.config import settings
from app.llm_clients.base import BaseLLMAdapter, LLMAdapterError, LLMResponse, retry_with_backoff
from app.llm_clients.cli_common import (
    CLIProcessError,
    CLIRateLimitError,
    CLITimeoutError,
    require_cli_installed,
    run_cli,
)
from app.llm_clients.mock import build_mock_response

# --- CLI가 바뀌면 이 블록만 고치면 된다 (docs/llm_clis.md §3 참조) ---
BINARY = "gemini"
DEFAULT_MODEL = "gemini-2.5-pro"
# Gemini CLI는 google_web_search 도구를 별도 플래그 없이 기본 제공한다 — 모델이 알아서 쓸지
# 말지 결정한다. 세 CLI 중 유일하게 "항상 사용 가능"이라 이 상수는 실제로는 "도구가 노출되어
# 있었다"는 뜻이지 "이번 호출에서 켰다"는 뜻이 아니다.
WEB_SEARCH_ENABLED = True
BASE_ARGS: list[str] = ["--output-format", "json"]
RETRYABLE_EXCEPTIONS: tuple[type[Exception], ...] = (
    CLITimeoutError,
    CLIProcessError,
    CLIRateLimitError,
)
LONG_DELAY_EXCEPTIONS: tuple[type[Exception], ...] = (CLIRateLimitError,)
MAX_RETRY_ATTEMPTS = 4
BASE_DELAY_SECONDS = 2.0
# ------------------------------------------------------------------------


class GeminiCLIAdapter(BaseLLMAdapter):
    provider_name = "gemini-cli"

    def __init__(self, model: str | None = None) -> None:
        self._model = model or DEFAULT_MODEL

    def query(self, prompt: str) -> LLMResponse:
        if settings.mock_llm:
            return build_mock_response(self.provider_name, self._model, prompt)

        require_cli_installed(BINARY, provider_name=self.provider_name)
        args = [BINARY, "-p", prompt, "-m", self._model, *BASE_ARGS]

        def _call() -> Any:
            return run_cli(
                args, provider_name=self.provider_name, timeout_seconds=settings.cli_timeout_sec
            )

        result = retry_with_backoff(
            _call,
            retryable_exceptions=RETRYABLE_EXCEPTIONS,
            long_delay_exceptions=LONG_DELAY_EXCEPTIONS,
            max_attempts=MAX_RETRY_ATTEMPTS,
            base_delay_seconds=BASE_DELAY_SECONDS,
            provider_name=self.provider_name,
        )
        return _parse_stdout(result.stdout, self._model)


def _parse_stdout(stdout: str, model: str) -> LLMResponse:
    try:
        data = json.loads(stdout)
    except json.JSONDecodeError as exc:
        raise LLMAdapterError(
            f"gemini-cli: --output-format json 파싱 실패: {exc}. 원본 앞부분: {stdout[:500]!r}"
        ) from exc

    error = data.get("error")
    if error:
        raise LLMAdapterError(f"gemini-cli: 오류 응답. error: {str(error)[:500]}")

    stats = data.get("stats") or {}
    models_stats = stats.get("models") or {}
    model_stats = models_stats.get(model) or next(iter(models_stats.values()), {})
    tokens = model_stats.get("tokens") or {}
    input_tokens = tokens.get("prompt")
    output_tokens = tokens.get("candidates")

    tools_stats = stats.get("tools") or {}
    # 실제 호출 여부가 통계에 잡히면 그 값을, 통계 필드가 없으면 "도구가 노출되어 있었다"는
    # 근사치(WEB_SEARCH_ENABLED)를 쓴다.
    search_stat = tools_stats.get("google_web_search")
    if isinstance(search_stat, dict):
        web_search_used = bool(search_stat.get("count", 0))
    else:
        web_search_used = WEB_SEARCH_ENABLED

    return LLMResponse(
        text=data.get("response", ""),
        # CLI는 구조화된 citation을 반환하지 않는다 — 파싱 엔진의 본문 URL 정규식 폴백이 주
        # 수단이 된다 (docs/llm_clis.md §3, 3-1 파싱 엔진).
        citations=[],
        web_search_used=web_search_used,
        input_tokens=input_tokens,
        output_tokens=output_tokens,
        cost_usd=None,
        model_string=model,
    )
