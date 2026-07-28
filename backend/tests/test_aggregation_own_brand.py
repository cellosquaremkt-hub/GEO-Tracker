"""brand_type=OWN_BRAND 프롬프트가 aggregate_week()의 SOV 계산(run_scope)에서 제외되는지 확인.

브랜드명을 직접 묻는 프롬프트는 그 브랜드 언급률이 구조적으로 100%에 가까워서, 일반 프롬프트와
합치면 SOV가 부풀려진다(2026-07-28 엑셀 프롬프트 대량 도입 배경 — CLAUDE.md, prompt.py 참조).
"""

from __future__ import annotations

from datetime import UTC, datetime

from sqlalchemy.orm import Session

from app.models.brand import Brand
from app.models.enums import BrandType, ExecutionStatus, Language, Priority, Sentiment, Target
from app.models.execution import ExecutionRun, Mention
from app.models.llm_provider import LLMProvider
from app.models.prompt import Prompt
from app.services.aggregation import aggregate_week

_WEEK = "2099-W01"


def _make_run(
    session: Session, *, prompt: Prompt, provider: LLMProvider, repeat_index: int
) -> ExecutionRun:
    run = ExecutionRun(
        batch_id=_WEEK,
        executed_at=datetime.now(UTC),
        prompt_id=prompt.id,
        llm_provider_id=provider.id,
        repeat_index=repeat_index,
        status=ExecutionStatus.SUCCESS,
        raw_response="dummy",
    )
    session.add(run)
    session.flush()
    return run


class TestOwnBrandExcludedFromSov:
    def test_own_brand_prompt_run_not_counted_in_total_runs(self, db_session: Session) -> None:
        own_brand = Brand(name="삼성SDS", is_own=True)
        session = db_session
        session.add(own_brand)
        provider = LLMProvider(
            name="claude-code-cli", model_string="sonnet", supports_web_search=True, is_active=True
        )
        session.add(provider)
        session.flush()

        normal_prompt = Prompt(
            text="물류 파트너 선정 기준이 무엇인가요?",
            intent="Test",
            target=Target.MANAGER,
            priority=Priority.MEDIUM,
            language=Language.KO,
            brand_type=BrandType.NON_BRAND_LONGTAIL,
        )
        own_brand_prompt = Prompt(
            text="삼성SDS 물류란 무엇인가요?",
            intent="Test",
            target=Target.COMMON,
            priority=Priority.MEDIUM,
            language=Language.KO,
            brand_type=BrandType.OWN_BRAND,
        )
        session.add_all([normal_prompt, own_brand_prompt])
        session.flush()

        normal_run = _make_run(session, prompt=normal_prompt, provider=provider, repeat_index=0)
        own_brand_run = _make_run(
            session, prompt=own_brand_prompt, provider=provider, repeat_index=0
        )
        session.add_all(
            [
                Mention(
                    execution_run_id=normal_run.id,
                    brand_id=own_brand.id,
                    mention_order=1,
                    sentiment=Sentiment.NEUTRAL,
                ),
                Mention(
                    execution_run_id=own_brand_run.id,
                    brand_id=own_brand.id,
                    mention_order=1,
                    sentiment=Sentiment.NEUTRAL,
                ),
            ]
        )
        session.flush()

        snapshots = aggregate_week(session, _WEEK)

        own_brand_overall = next(
            s for s in snapshots if s.brand_id == own_brand.id and s.llm_provider_id is None
        )
        # OWN_BRAND 프롬프트의 실행은 분모(run_scope)에서 아예 빠져야 한다 — 2건이 아니라 1건.
        assert own_brand_overall.total_runs == 1
        assert own_brand_overall.sov == 100

    def test_prompt_without_brand_type_still_counted(self, db_session: Session) -> None:
        """brand_type이 아직 없는(NULL) 기존 프롬프트는 하위호환으로 계속 집계 대상이다."""
        own_brand = Brand(name="첼로스퀘어", is_own=True)
        session = db_session
        session.add(own_brand)
        provider = LLMProvider(
            name="claude-code-cli", model_string="sonnet", supports_web_search=True, is_active=True
        )
        session.add(provider)
        session.flush()

        legacy_prompt = Prompt(
            text="레거시 프롬프트(brand_type 미지정)",
            intent="Test",
            target=Target.MANAGER,
            priority=Priority.MEDIUM,
            language=Language.KO,
        )
        session.add(legacy_prompt)
        session.flush()

        run = _make_run(session, prompt=legacy_prompt, provider=provider, repeat_index=0)
        session.add(
            Mention(
                execution_run_id=run.id,
                brand_id=own_brand.id,
                mention_order=1,
                sentiment=Sentiment.POSITIVE,
            )
        )
        session.flush()

        snapshots = aggregate_week(session, _WEEK)
        overall = next(
            s for s in snapshots if s.brand_id == own_brand.id and s.llm_provider_id is None
        )
        assert overall.total_runs == 1
        assert overall.sov == 100
