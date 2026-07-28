from __future__ import annotations

from datetime import UTC, datetime

from sqlalchemy.orm import Session

from app.models.brand import Brand
from app.models.enums import ExecutionStatus, Language, Priority, Sentiment, Target
from app.models.execution import ExecutionRun, Mention
from app.models.llm_provider import LLMProvider
from app.models.prompt import Prompt


class TestListMentions:
    def test_returns_bulk_mentions_for_week(self, client, db_session: Session) -> None:
        brand = Brand(name="삼성SDS", is_own=True)
        provider = LLMProvider(name="claude-code-cli", model_string="sonnet")
        prompt = Prompt(
            text="테스트 프롬프트",
            intent="Test",
            target=Target.MANAGER,
            priority=Priority.MEDIUM,
            language=Language.KO,
        )
        db_session.add_all([brand, provider, prompt])
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
                brand_id=brand.id,
                mention_order=1,
                sentiment=Sentiment.POSITIVE,
                sentiment_evidence="근거 문구",
            )
        )
        db_session.flush()

        response = client.get("/mentions?week=2026-W28")

        assert response.status_code == 200
        body = response.get_json()
        assert len(body) == 1
        assert body[0]["prompt_id"] == prompt.id
        assert body[0]["prompt_text"] == "테스트 프롬프트"
        assert body[0]["prompt_intent"] == "Test"
        assert body[0]["llm_provider_name"] == "claude-code-cli"
        assert body[0]["execution_run_id"] == run.id
        assert body[0]["brand_id"] == brand.id
        assert body[0]["brand_name"] == "삼성SDS"
        assert body[0]["mention_order"] == 1
        assert body[0]["sentiment"] == "positive"
        assert body[0]["sentiment_evidence"] == "근거 문구"

    def test_excludes_failed_runs(self, client, db_session: Session) -> None:
        provider = LLMProvider(name="claude-code-cli", model_string="sonnet")
        prompt = Prompt(
            text="테스트",
            intent="Test",
            target=Target.MANAGER,
            priority=Priority.MEDIUM,
            language=Language.KO,
        )
        db_session.add_all([provider, prompt])
        db_session.flush()
        db_session.add(
            ExecutionRun(
                batch_id="2026-W28",
                executed_at=datetime.now(UTC),
                prompt_id=prompt.id,
                llm_provider_id=provider.id,
                repeat_index=0,
                status=ExecutionStatus.FAILED,
            )
        )
        db_session.flush()

        response = client.get("/mentions?week=2026-W28")

        assert response.status_code == 200
        assert response.get_json() == []

    def test_empty_week_returns_empty_list(self, client) -> None:
        response = client.get("/mentions?week=2099-W01")
        assert response.status_code == 200
        assert response.get_json() == []

    def test_defaults_to_current_week_when_omitted(self, client, db_session: Session) -> None:
        from app.services.week_utils import compute_current_week_label

        current_week = compute_current_week_label()
        brand = Brand(name="첼로스퀘어", is_own=True)
        provider = LLMProvider(name="codex-cli", model_string="gpt")
        prompt = Prompt(
            text="현재 주 프롬프트",
            intent="Test",
            target=Target.MANAGER,
            priority=Priority.MEDIUM,
            language=Language.KO,
        )
        db_session.add_all([brand, provider, prompt])
        db_session.flush()

        run = ExecutionRun(
            batch_id=current_week,
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
                brand_id=brand.id,
                mention_order=1,
                sentiment=Sentiment.NEUTRAL,
            )
        )
        db_session.flush()

        response = client.get("/mentions")

        assert response.status_code == 200
        body = response.get_json()
        assert len(body) == 1
        assert body[0]["prompt_id"] == prompt.id
