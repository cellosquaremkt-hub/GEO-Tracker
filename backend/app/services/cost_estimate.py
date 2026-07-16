"""배치 실행 전 예상 호출 수 — 프롬프트 수 x LLM 수 x REPEAT_COUNT.

측정 채널이 구독 좌석 기반 CLI라 토큰 단가를 알 수 없다(Codex/Gemini CLI는 토큰 수 자체를
안 준다 — docs/llm_clis.md 참조). 그래서 사전 추정은 달러 금액이 아니라 "호출이 몇 번 나갈
것인가"로 잡는다 — 이 값이 구독 좌석의 rate limit을 넘는지 확인하는 용도다
(batch_runner.trigger_batch의 MAX_CALLS_PER_BATCH 가드가 이 값을 근거로 판단한다).
"""

from __future__ import annotations

from dataclasses import dataclass, field

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.models.llm_provider import LLMProvider
from app.models.prompt import Prompt
from app.services.batch_config_service import get_repeat_count


@dataclass(frozen=True)
class EstimateResult:
    total_calls: int
    per_provider_calls: dict[str, int] = field(default_factory=dict)


def estimate_batch_calls(session: Session) -> EstimateResult:
    active_prompt_count = session.execute(
        select(func.count()).select_from(Prompt).where(Prompt.is_active.is_(True))
    ).scalar_one()
    provider_names = (
        session.execute(select(LLMProvider.name).where(LLMProvider.is_active.is_(True)))
        .scalars()
        .all()
    )

    repeat_count = get_repeat_count(session)
    calls_per_provider = active_prompt_count * repeat_count
    per_provider = {name: calls_per_provider for name in provider_names}
    total_calls = calls_per_provider * len(provider_names)
    return EstimateResult(total_calls=total_calls, per_provider_calls=per_provider)
