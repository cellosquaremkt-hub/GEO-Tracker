from __future__ import annotations

from datetime import UTC, datetime

from sqlalchemy.orm import Session

from app.models.brand import Brand
from app.models.enums import ExecutionStatus, Language, Priority, Sentiment, Target
from app.models.execution import ExecutionRun, Mention
from app.models.llm_provider import LLMProvider
from app.models.prompt import Prompt


def _make_run(
    db_session: Session,
    *,
    prompt: Prompt,
    provider: LLMProvider,
    repeat_index: int,
    week: str = "2026-W28",
    status: ExecutionStatus = ExecutionStatus.SUCCESS,
) -> ExecutionRun:
    run = ExecutionRun(
        batch_id=week,
        executed_at=datetime.now(UTC),
        prompt_id=prompt.id,
        llm_provider_id=provider.id,
        repeat_index=repeat_index,
        status=status,
    )
    db_session.add(run)
    db_session.flush()
    return run


class TestWeeklyReportSummary:
    def test_counts_runs_by_status(self, client, db_session: Session) -> None:
        provider = LLMProvider(name="claude-code-cli", model_string="sonnet")
        prompt = Prompt(
            text="P",
            intent="Test",
            target=Target.MANAGER,
            priority=Priority.HIGH,
            language=Language.KO,
        )
        db_session.add_all([provider, prompt])
        db_session.flush()
        _make_run(db_session, prompt=prompt, provider=provider, repeat_index=0)
        _make_run(
            db_session,
            prompt=prompt,
            provider=provider,
            repeat_index=1,
            status=ExecutionStatus.FAILED,
        )

        response = client.get("/reports/weekly?week=2026-W28")

        assert response.status_code == 200
        summary = response.get_json()["summary"]
        assert summary["total_execution_runs"] == 2
        assert summary["success_count"] == 1
        assert summary["failed_count"] == 1


class TestVulnerablePrompts:
    def test_uncovered_prompt_flagged_as_not_exposed(self, client, db_session: Session) -> None:
        own = Brand(name="삼성SDS", is_own=True)
        competitor = Brand(name="LX Pantos", is_own=False)
        provider = LLMProvider(name="claude-code-cli", model_string="sonnet")
        prompt = Prompt(
            text="미노출 프롬프트",
            intent="Test",
            target=Target.MANAGER,
            priority=Priority.HIGH,
            language=Language.KO,
        )
        db_session.add_all([own, competitor, provider, prompt])
        db_session.flush()
        run = _make_run(db_session, prompt=prompt, provider=provider, repeat_index=0)
        db_session.add(
            Mention(
                execution_run_id=run.id,
                brand_id=competitor.id,
                mention_order=1,
                sentiment=Sentiment.POSITIVE,
            )
        )
        db_session.flush()

        response = client.get("/reports/weekly?week=2026-W28")

        assert response.status_code == 200
        vulnerable = response.get_json()["vulnerable_prompts"]
        assert len(vulnerable) == 1
        assert vulnerable[0]["prompt_id"] == prompt.id
        assert vulnerable[0]["reason"] == "미노출"

    def test_negative_only_own_mentions_flagged(self, client, db_session: Session) -> None:
        own = Brand(name="삼성SDS", is_own=True)
        provider = LLMProvider(name="claude-code-cli", model_string="sonnet")
        prompt = Prompt(
            text="부정 언급 프롬프트",
            intent="Test",
            target=Target.MANAGER,
            priority=Priority.MEDIUM,
            language=Language.KO,
        )
        db_session.add_all([own, provider, prompt])
        db_session.flush()
        run = _make_run(db_session, prompt=prompt, provider=provider, repeat_index=0)
        db_session.add(
            Mention(
                execution_run_id=run.id,
                brand_id=own.id,
                mention_order=1,
                sentiment=Sentiment.NEGATIVE,
            )
        )
        db_session.flush()

        response = client.get("/reports/weekly?week=2026-W28")

        vulnerable = response.get_json()["vulnerable_prompts"]
        assert len(vulnerable) == 1
        assert vulnerable[0]["reason"] == "부정적 언급만 존재"

    def test_positive_own_mention_is_not_vulnerable(self, client, db_session: Session) -> None:
        own = Brand(name="삼성SDS", is_own=True)
        provider = LLMProvider(name="claude-code-cli", model_string="sonnet")
        prompt = Prompt(
            text="정상 프롬프트",
            intent="Test",
            target=Target.MANAGER,
            priority=Priority.LOW,
            language=Language.KO,
        )
        db_session.add_all([own, provider, prompt])
        db_session.flush()
        run = _make_run(db_session, prompt=prompt, provider=provider, repeat_index=0)
        db_session.add(
            Mention(
                execution_run_id=run.id,
                brand_id=own.id,
                mention_order=1,
                sentiment=Sentiment.POSITIVE,
            )
        )
        db_session.flush()

        response = client.get("/reports/weekly?week=2026-W28")

        assert response.get_json()["vulnerable_prompts"] == []

    def test_prompt_without_runs_this_week_is_excluded(self, client, db_session: Session) -> None:
        prompt = Prompt(
            text="아직 실행 안 됨",
            intent="Test",
            target=Target.MANAGER,
            priority=Priority.HIGH,
            language=Language.KO,
        )
        db_session.add(prompt)
        db_session.flush()

        response = client.get("/reports/weekly?week=2026-W28")

        assert response.get_json()["vulnerable_prompts"] == []

    def test_sorted_by_priority_then_prompt_id(self, client, db_session: Session) -> None:
        provider = LLMProvider(name="claude-code-cli", model_string="sonnet")
        low = Prompt(
            text="낮은 우선순위",
            intent="Test",
            target=Target.MANAGER,
            priority=Priority.LOW,
            language=Language.KO,
        )
        high = Prompt(
            text="높은 우선순위",
            intent="Test",
            target=Target.MANAGER,
            priority=Priority.HIGH,
            language=Language.KO,
        )
        db_session.add_all([provider, low, high])
        db_session.flush()
        _make_run(db_session, prompt=low, provider=provider, repeat_index=0)
        _make_run(db_session, prompt=high, provider=provider, repeat_index=0)

        response = client.get("/reports/weekly?week=2026-W28")

        vulnerable = response.get_json()["vulnerable_prompts"]
        assert [v["prompt_id"] for v in vulnerable] == [high.id, low.id]


class TestCompetitorAdvantagePrompts:
    def test_competitor_with_better_avg_rank_flagged(self, client, db_session: Session) -> None:
        own = Brand(name="삼성SDS", is_own=True)
        competitor = Brand(name="LX Pantos", is_own=False)
        provider = LLMProvider(name="claude-code-cli", model_string="sonnet")
        prompt = Prompt(
            text="경쟁 프롬프트",
            intent="Test",
            target=Target.MANAGER,
            priority=Priority.MEDIUM,
            language=Language.KO,
        )
        db_session.add_all([own, competitor, provider, prompt])
        db_session.flush()
        run = _make_run(db_session, prompt=prompt, provider=provider, repeat_index=0)
        db_session.add_all(
            [
                Mention(
                    execution_run_id=run.id,
                    brand_id=own.id,
                    mention_order=3,
                    sentiment=Sentiment.NEUTRAL,
                ),
                Mention(
                    execution_run_id=run.id,
                    brand_id=competitor.id,
                    mention_order=1,
                    sentiment=Sentiment.NEUTRAL,
                ),
            ]
        )
        db_session.flush()

        response = client.get("/reports/weekly?week=2026-W28")

        advantage = response.get_json()["competitor_advantage_prompts"]
        assert len(advantage) == 1
        assert advantage[0]["leading_competitor_name"] == "LX Pantos"
        assert advantage[0]["own_avg_rank"] == "3"
        assert advantage[0]["leading_competitor_avg_rank"] == "1"

    def test_own_better_rank_not_flagged(self, client, db_session: Session) -> None:
        own = Brand(name="삼성SDS", is_own=True)
        competitor = Brand(name="LX Pantos", is_own=False)
        provider = LLMProvider(name="claude-code-cli", model_string="sonnet")
        prompt = Prompt(
            text="우리가 우위",
            intent="Test",
            target=Target.MANAGER,
            priority=Priority.MEDIUM,
            language=Language.KO,
        )
        db_session.add_all([own, competitor, provider, prompt])
        db_session.flush()
        run = _make_run(db_session, prompt=prompt, provider=provider, repeat_index=0)
        db_session.add_all(
            [
                Mention(
                    execution_run_id=run.id,
                    brand_id=own.id,
                    mention_order=1,
                    sentiment=Sentiment.NEUTRAL,
                ),
                Mention(
                    execution_run_id=run.id,
                    brand_id=competitor.id,
                    mention_order=3,
                    sentiment=Sentiment.NEUTRAL,
                ),
            ]
        )
        db_session.flush()

        response = client.get("/reports/weekly?week=2026-W28")

        assert response.get_json()["competitor_advantage_prompts"] == []
