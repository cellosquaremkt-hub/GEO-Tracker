from __future__ import annotations

from datetime import UTC, datetime
from decimal import Decimal

from sqlalchemy.orm import Session

from app.models.brand import Brand
from app.models.enums import ExecutionStatus, Language, Priority, Sentiment, Target
from app.models.execution import ExecutionRun, Mention
from app.models.llm_provider import LLMProvider
from app.models.prompt import Prompt
from app.models.snapshot import WeeklySnapshot


def _seed_week(db_session: Session, week: str) -> dict[str, int]:
    own = Brand(name="삼성SDS", is_own=True)
    competitor_a = Brand(name="LX Pantos", is_own=False)
    competitor_b = Brand(name="Flexport", is_own=False)
    db_session.add_all([own, competitor_a, competitor_b])
    db_session.flush()

    db_session.add_all(
        [
            WeeklySnapshot(
                week_label=week,
                brand_id=own.id,
                llm_provider_id=None,
                sov=Decimal("30.000"),
                total_runs=10,
            ),
            WeeklySnapshot(
                week_label=week,
                brand_id=competitor_a.id,
                llm_provider_id=None,
                sov=Decimal("50.000"),
                total_runs=10,
            ),
            WeeklySnapshot(
                week_label=week,
                brand_id=competitor_b.id,
                llm_provider_id=None,
                sov=Decimal("20.000"),
                total_runs=10,
            ),
        ]
    )
    db_session.flush()
    return {"own": own.id, "competitor_a": competitor_a.id, "competitor_b": competitor_b.id}


class TestDashboardSummary:
    def test_rank_and_sov_with_no_previous_week(self, client, db_session: Session) -> None:
        _seed_week(db_session, "2026-W28")

        response = client.get("/dashboard/summary?week=2026-W28")

        assert response.status_code == 200
        body = response.get_json()
        assert body["total_sov"] == "30.000"
        # 경쟁사 A(50) > 우리(30) > 경쟁사 B(20) → 2위.
        assert body["rank"] == 2
        assert body["total_ranked_entities"] == 3
        assert body["sov_delta"] is None  # 직전 주 데이터가 없다.

    def test_sov_delta_computed_from_previous_week(self, client, db_session: Session) -> None:
        ids = _seed_week(db_session, "2026-W27")
        db_session.add(
            WeeklySnapshot(
                week_label="2026-W28",
                brand_id=ids["own"],
                llm_provider_id=None,
                sov=Decimal("45.000"),
                total_runs=10,
            )
        )
        db_session.flush()

        response = client.get("/dashboard/summary?week=2026-W28")

        assert response.status_code == 200
        body = response.get_json()
        assert body["total_sov"] == "45.000"
        assert body["sov_delta"] == "15.000"  # 45 - 30

    def test_negative_mention_count(self, client, db_session: Session) -> None:
        ids = _seed_week(db_session, "2026-W28")
        provider = LLMProvider(name="claude-code-cli", model_string="sonnet")
        prompt = Prompt(
            text="테스트 프롬프트",
            intent="Test",
            target=Target.MANAGER,
            priority=Priority.MEDIUM,
            language=Language.KO,
        )
        db_session.add_all([provider, prompt])
        db_session.flush()
        run = ExecutionRun(
            batch_id="2026-W28",
            executed_at=datetime.now(UTC),
            prompt_id=prompt.id,
            llm_provider_id=provider.id,
            repeat_index=0,
            status=ExecutionStatus.SUCCESS,
        )
        db_session.add(run)
        db_session.flush()
        db_session.add(
            Mention(
                execution_run_id=run.id,
                brand_id=ids["own"],
                mention_order=1,
                sentiment=Sentiment.NEGATIVE,
                sentiment_evidence="부정적 근거",
            )
        )
        db_session.flush()

        response = client.get("/dashboard/summary?week=2026-W28")

        assert response.status_code == 200
        assert response.get_json()["negative_mention_count"] == 1
