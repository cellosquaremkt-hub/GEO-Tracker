from __future__ import annotations

import csv
import io
from datetime import UTC, datetime

from sqlalchemy.orm import Session

from app.models.brand import Brand
from app.models.enums import ExecutionStatus, Language, Priority, Sentiment, Target
from app.models.execution import ExecutionRun, Mention
from app.models.llm_provider import LLMProvider
from app.models.prompt import Prompt


class TestExportCsv:
    def test_returns_csv_with_expected_rows(self, client, db_session: Session) -> None:
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

        response = client.get("/export/csv?week=2026-W28")

        assert response.status_code == 200
        assert response.headers["content-type"].startswith("text/csv")
        assert "attachment" in response.headers["content-disposition"]

        rows = list(csv.DictReader(io.StringIO(response.get_data(as_text=True))))
        assert len(rows) == 1
        assert rows[0]["brand_name"] == "삼성SDS"
        assert rows[0]["sentiment"] == "positive"
        assert rows[0]["is_own"] == "True"
        assert rows[0]["prompt_id"] == str(prompt.id)

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

        response = client.get("/export/csv?week=2026-W28")

        assert response.status_code == 200
        rows = list(csv.DictReader(io.StringIO(response.get_data(as_text=True))))
        assert rows == []

    def test_empty_week_returns_header_only(self, client) -> None:
        response = client.get("/export/csv?week=2099-W01")
        assert response.status_code == 200
        lines = response.get_data(as_text=True).strip().splitlines()
        assert len(lines) == 1  # 헤더만.
