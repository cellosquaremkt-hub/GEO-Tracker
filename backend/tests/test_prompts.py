from __future__ import annotations

from datetime import UTC, datetime

from sqlalchemy.orm import Session

from app.models.brand import Brand
from app.models.enums import ExecutionStatus, Language, Priority, Sentiment, Target
from app.models.execution import Citation, ExecutionRun, Mention
from app.models.llm_provider import LLMProvider
from app.models.prompt import Prompt


class TestListPrompts:
    def test_no_filters_returns_all(self, client, db_session: Session) -> None:
        db_session.add_all(
            [
                Prompt(
                    text="P1",
                    intent="AI Strategy",
                    target=Target.C_LEVEL,
                    priority=Priority.HIGH,
                    language=Language.EN,
                ),
                Prompt(
                    text="P2",
                    intent="B/L 기초",
                    target=Target.JUNIOR,
                    priority=Priority.LOW,
                    language=Language.KO,
                    is_active=False,
                ),
            ]
        )
        db_session.flush()

        response = client.get("/prompts")
        assert response.status_code == 200
        assert len(response.get_json()) == 2

    def test_filters_combine_with_and(self, client, db_session: Session) -> None:
        db_session.add_all(
            [
                Prompt(
                    text="P1",
                    intent="AI Strategy",
                    target=Target.C_LEVEL,
                    priority=Priority.HIGH,
                    language=Language.EN,
                ),
                Prompt(
                    text="P2",
                    intent="AI Strategy",
                    target=Target.MANAGER,
                    priority=Priority.HIGH,
                    language=Language.EN,
                ),
            ]
        )
        db_session.flush()

        response = client.get(
            "/prompts", query_string={"intent": "AI Strategy", "target": "c-level"}
        )
        assert response.status_code == 200
        body = response.get_json()
        assert len(body) == 1
        assert body[0]["text"] == "P1"

    def test_is_active_filter(self, client, db_session: Session) -> None:
        db_session.add_all(
            [
                Prompt(
                    text="Active",
                    intent="Test",
                    target=Target.MANAGER,
                    priority=Priority.MEDIUM,
                    language=Language.KO,
                    is_active=True,
                ),
                Prompt(
                    text="Inactive",
                    intent="Test",
                    target=Target.MANAGER,
                    priority=Priority.MEDIUM,
                    language=Language.KO,
                    is_active=False,
                ),
            ]
        )
        db_session.flush()

        response = client.get("/prompts?is_active=false")
        assert response.status_code == 200
        body = response.get_json()
        assert len(body) == 1
        assert body[0]["text"] == "Inactive"


class TestPromptDetail:
    def test_404_for_unknown_prompt(self, client) -> None:
        response = client.get("/prompts/999999/detail?week=2026-W28")
        assert response.status_code == 404

    def test_returns_highlights_mentions_and_citations(self, client, db_session: Session) -> None:
        brand = Brand(name="삼성SDS", is_own=True)
        provider = LLMProvider(name="claude-code-cli", model_string="sonnet")
        prompt = Prompt(
            text="삼성SDS 추천해줘",
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
            raw_response="삼성SDS는 신뢰받는 선도 서비스입니다.",
        )
        db_session.add(run)
        db_session.flush()
        db_session.add(
            Mention(
                execution_run_id=run.id,
                brand_id=brand.id,
                mention_order=1,
                sentiment=Sentiment.POSITIVE,
                sentiment_evidence="신뢰받는 선도",
            )
        )
        db_session.add(
            Citation(
                execution_run_id=run.id,
                url="https://samsungsds.com/page",
                domain="samsungsds.com",
                matched_brand_id=brand.id,
            )
        )
        db_session.flush()

        response = client.get(f"/prompts/{prompt.id}/detail?week=2026-W28")

        assert response.status_code == 200
        body = response.get_json()
        assert body["prompt_text"] == "삼성SDS 추천해줘"
        assert len(body["executions"]) == 1
        execution = body["executions"][0]
        assert execution["llm_provider_name"] == "claude-code-cli"
        assert execution["raw_response"] == "삼성SDS는 신뢰받는 선도 서비스입니다."
        assert len(execution["highlights"]) == 1
        assert execution["highlights"][0]["matched_text"] == "삼성SDS"
        assert execution["highlights"][0]["start"] == 0
        assert execution["mentions"][0]["sentiment"] == "positive"
        assert execution["citations"][0]["matched_brand_name"] == "삼성SDS"

    def test_no_executions_for_week_returns_empty_list(self, client, db_session: Session) -> None:
        prompt = Prompt(
            text="언급 없음",
            intent="Test",
            target=Target.MANAGER,
            priority=Priority.MEDIUM,
            language=Language.KO,
        )
        db_session.add(prompt)
        db_session.flush()

        response = client.get(f"/prompts/{prompt.id}/detail?week=2026-W28")

        assert response.status_code == 200
        assert response.get_json()["executions"] == []
