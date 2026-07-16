"""Claude Code CLI 어댑터 — 구독 좌석 기반 측정 채널(API 키 아님).

조사 근거: docs/llm_clis.md §1 (참고 프로젝트 20260709, 2026-07-10 확인). 인증은
`claude setup-token`으로 발급한 장기 OAuth 토큰(CLAUDE_CODE_OAUTH_TOKEN)을 쓴다 —
docs/operations.md 참조.
"""

from __future__ import annotations

import json
from decimal import Decimal, InvalidOperation
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

# --- CLI가 바뀌면 이 블록만 고치면 된다 (docs/llm_clis.md §1 참조) ---
BINARY = "claude"
DEFAULT_MODEL = "sonnet"
# `--bare`는 뺐다: 실 CLI 파일럿(참고 프로젝트, 2026-07-13, Claude Code CLI v2.1.207)에서
# `--bare` 모드가 `claude setup-token`으로 발급한 `CLAUDE_CODE_OAUTH_TOKEN`을 인식하지 못하고
# "Not logged in"을 반환하는 것을 실측으로 확인했다(같은 토큰으로 `--bare` 없이는 정상 인증됨).
# CLI_WORKDIR가 항상 비어있는 전용 디렉터리라 프로젝트 수준 CLAUDE.md/AGENTS.md 오염 위험은
# 여전히 없지만, 사용자 계정 수준의 스킬/MCP/메모리가 로드될 잔여 위험은 남는다 —
# docs/llm_clis.md §1(a), docs/metrics.md §7 측정 한계에 기록. `--tools`/`--allowedTools`로
# WebSearch만 허용하는 것은 `--bare` 없이도 그대로 동작함을 확인했다(headless라 승인 프롬프트에
# 응답할 수 없으므로 --allowedTools로 사전 승인은 계속 필요).
WEB_SEARCH_ENABLED = True
BASE_ARGS: list[str] = [
    "--output-format",
    "json",
    "--tools",
    "WebSearch",
    "--allowedTools",
    "WebSearch",
]
RETRYABLE_EXCEPTIONS: tuple[type[Exception], ...] = (
    CLITimeoutError,
    CLIProcessError,
    CLIRateLimitError,
)
LONG_DELAY_EXCEPTIONS: tuple[type[Exception], ...] = (CLIRateLimitError,)
MAX_RETRY_ATTEMPTS = 4
BASE_DELAY_SECONDS = 2.0
# ------------------------------------------------------------------------


class ClaudeCodeCLIAdapter(BaseLLMAdapter):
    provider_name = "claude-code-cli"

    def __init__(self, model: str | None = None) -> None:
        self._model = model or DEFAULT_MODEL

    def query(self, prompt: str) -> LLMResponse:
        if settings.mock_llm:
            return build_mock_response(self.provider_name, self._model, prompt)

        require_cli_installed(BINARY, provider_name=self.provider_name)
        args = [BINARY, "-p", prompt, "--model", self._model, *BASE_ARGS]

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
            f"claude-code-cli: --output-format json 파싱 실패: {exc}. 원본 앞부분: {stdout[:500]!r}"
        ) from exc

    if data.get("is_error"):
        result_preview = data.get("result", "")[:500]
        raise LLMAdapterError(f"claude-code-cli: is_error=true. result: {result_preview}")

    usage = data.get("usage") or {}
    total_cost_usd = data.get("total_cost_usd")
    cost_usd: Decimal | None = None
    if total_cost_usd is not None:
        try:
            cost_usd = Decimal(str(total_cost_usd))
        except InvalidOperation:
            cost_usd = None

    return LLMResponse(
        text=data.get("result", ""),
        # CLI는 구조화된 citation을 반환하지 않는다 — 파싱 엔진의 본문 URL 정규식 폴백이 주
        # 수단이 된다 (docs/llm_clis.md §3, 3-1 파싱 엔진).
        citations=[],
        # 비-스트리밍 json 출력에는 도구 호출 여부 필드가 없어 "이 호출에서 WebSearch가 허용되어
        # 있었는지"의 근사치다 — 실제로 모델이 검색했는지는 개별 응답 단위로 확인할 수 없다
        # (docs/llm_clis.md §1 알려진 한계).
        web_search_used=WEB_SEARCH_ENABLED,
        input_tokens=usage.get("input_tokens"),
        output_tokens=usage.get("output_tokens"),
        cost_usd=cost_usd,
        model_string=model,
    )
