"""LLM 프로바이더 어댑터 공통 인터페이스.

모든 어댑터는 BaseLLMAdapter를 구현하고 query()에서 LLMResponse를 반환한다. MOCK_LLM=true일
때의 목 응답 반환, 타임아웃/레이트리밋 재시도, 인증 부재 시 즉시 실패는 각 어댑터가 이 모듈의
유틸을 사용해 처리한다.

활성 어댑터는 구독 기반 코딩 에이전트 CLI 3종(Claude Code/Codex/Gemini CLI)뿐이다 —
app/llm_clients/{claude_code,codex,gemini}_cli_adapter.py. 참고 프로젝트(20260709)의 토큰 단가
기반 SDK 어댑터(OpenAI/Gemini/Anthropic/Perplexity API)는 이 재개발에서는 이식하지 않는다 —
회사 사정으로 그 API 키 자체가 없어 실제로 쓰이지 않는 경로다(docs/backlog.md 참조, API 키를
다시 받으면 그때 이식한다).

CLI는 토큰/비용을 제공하지 않는 경우가 흔해 input_tokens/output_tokens/cost_usd는 전부
nullable이다 — Claude Code CLI만 --output-format json의 usage/total_cost_usd로 실측치를
제공하고, Codex/Gemini CLI는 항상 None이다.

이 모듈은 Flask(동기 WSGI)와 worker 데몬(동기 subprocess) 양쪽에서 쓰인다 — asyncio 의존성이
없다. retry_with_backoff의 대기는 time.sleep()이며, 이 함수를 호출하는 쪽(어댑터의 query())이
동기 함수이므로 worker 데몬의 ThreadPoolExecutor 워커 스레드 안에서 블로킹해도 문제없다(그
스레드 하나가 그 호출 하나를 전담하는 구조 — migration_flask_postgres.md §2.3 참조).
"""

from __future__ import annotations

import abc
import random
import time
from collections.abc import Callable
from dataclasses import dataclass, field
from decimal import Decimal
from typing import TypeVar

T = TypeVar("T")


@dataclass
class LLMResponse:
    text: str
    citations: list[str] = field(default_factory=list)
    web_search_used: bool = False
    input_tokens: int | None = None
    output_tokens: int | None = None
    cost_usd: Decimal | None = None
    model_string: str = ""


class LLMAdapterError(Exception):
    """모든 어댑터 예외의 공통 기반 클래스."""


class MissingAPIKeyError(LLMAdapterError):
    """API 키/인증이 비어 있을 때 즉시 발생시킨다 — 재시도하지 않는다."""


class LLMRequestError(LLMAdapterError):
    """타임아웃/레이트리밋/일시 서버 오류가 재시도 후에도 계속될 때 발생시킨다."""


class BaseLLMAdapter(abc.ABC):
    provider_name: str

    @abc.abstractmethod
    def query(self, prompt: str) -> LLMResponse:
        """프롬프트를 실행하고 정규화된 LLMResponse를 반환한다."""


def retry_with_backoff(
    func: Callable[[], T],
    *,
    retryable_exceptions: tuple[type[Exception], ...],
    max_attempts: int = 4,
    base_delay_seconds: float = 1.0,
    long_delay_exceptions: tuple[type[Exception], ...] = (),
    long_delay_multiplier: float = 5.0,
    provider_name: str = "",
) -> T:
    """지수 백오프 + 지터로 재시도한다.

    retryable_exceptions에 속하지 않는 예외(예: 인증 오류)는 즉시 그대로 전파한다 —
    재시도해도 성공할 수 없는 오류이기 때문이다.

    long_delay_exceptions에 속하는 예외(예: 좌석 사용량 한도 초과류의 CLI 레이트리밋)는
    base_delay_seconds에 long_delay_multiplier를 곱해 훨씬 긴 간격으로 재시도한다 — 수 분~수
    시간 단위로 리셋되는 구독 좌석 rate limit에는 초 단위 백오프가 무의미하기 때문이다.
    """
    last_exc: Exception | None = None
    for attempt in range(max_attempts):
        try:
            return func()
        except retryable_exceptions as exc:
            last_exc = exc
            if attempt == max_attempts - 1:
                break
            effective_base = (
                base_delay_seconds * long_delay_multiplier
                if isinstance(exc, long_delay_exceptions)
                else base_delay_seconds
            )
            delay = effective_base * (2**attempt) + random.uniform(0, effective_base)
            time.sleep(delay)
    raise LLMRequestError(
        f"{provider_name}: {max_attempts}회 재시도 후에도 요청이 실패했습니다: {last_exc}"
    ) from last_exc
