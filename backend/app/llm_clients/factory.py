"""프로바이더 이름(brand/llm_provider.name과 동일한 표기) -> 어댑터 팩토리.

활성 측정 채널은 구독 좌석 기반 CLI 3종뿐이다(claude-code-cli/codex-cli/gemini-cli). 참고
프로젝트(20260709)의 레거시 SDK(API 키) 어댑터는 이 재개발에서 이식하지 않는다 — 회사 사정으로
그 API 키 자체가 없어 실제로 쓰이지 않는 경로다(docs/backlog.md 참조).
"""

from __future__ import annotations

from app.llm_clients.base import BaseLLMAdapter
from app.llm_clients.claude_code_cli_adapter import ClaudeCodeCLIAdapter
from app.llm_clients.codex_cli_adapter import CodexCLIAdapter
from app.llm_clients.gemini_cli_adapter import GeminiCLIAdapter

_ADAPTER_CLASSES: dict[str, type[BaseLLMAdapter]] = {
    "claude-code-cli": ClaudeCodeCLIAdapter,
    "codex-cli": CodexCLIAdapter,
    "gemini-cli": GeminiCLIAdapter,
}


def get_adapter(provider_name: str, *, model: str | None = None) -> BaseLLMAdapter:
    try:
        adapter_cls = _ADAPTER_CLASSES[provider_name]
    except KeyError:
        raise ValueError(
            f"알 수 없는 LLM 프로바이더 '{provider_name}'. 지원 목록: {sorted(_ADAPTER_CLASSES)}"
        ) from None
    return adapter_cls(model=model)
