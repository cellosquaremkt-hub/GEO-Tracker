from __future__ import annotations

import time

import pytest
from sqlalchemy.orm import Session, sessionmaker

from app.core.config import settings
from app.models.brand import Brand
from app.models.enums import Language, Priority, Target
from app.models.llm_provider import LLMProvider
from app.models.prompt import Prompt
from app.worker.daemon import WeeklyBatchWorker

pytestmark = pytest.mark.usefixtures("clean_batch_tables")

ADMIN_HEADERS = {"X-Admin-Api-Key": settings.admin_api_key}


def _seed_minimal_dataset(session_factory: sessionmaker[Session]) -> None:
    with session_factory() as session:
        session.add(Brand(name="삼성SDS", is_own=True))
        session.add(
            LLMProvider(name="claude-code-cli", model_string="sonnet", supports_web_search=True)
        )
        session.add(
            Prompt(
                text="테스트 프롬프트",
                intent="Test",
                target=Target.MANAGER,
                priority=Priority.MEDIUM,
                language=Language.KO,
            )
        )
        session.commit()


@pytest.fixture(autouse=True)
def _fast_batch_settings(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(settings, "mock_llm", True)
    monkeypatch.setattr(settings, "repeat_count", 1)
    monkeypatch.setattr(settings, "claude_code_concurrency_limit", 4)


def _run_worker_to_completion(
    session_factory: sessionmaker[Session], batch_id: str, timeout: float = 5.0
):
    from app.services.batch_runner import get_batch_status

    worker = WeeklyBatchWorker(session_factory)
    deadline = time.monotonic() + timeout
    try:
        while time.monotonic() < deadline:
            worker.poll_once()
            with session_factory() as session:
                status = get_batch_status(session, batch_id)
            if status.pending == 0 and status.running == 0:
                worker.poll_once()
                return status
            time.sleep(0.05)
    finally:
        worker.shutdown()
    raise AssertionError(f"batch_id={batch_id} 처리가 {timeout}초 안에 끝나지 않았습니다.")


class TestAuth:
    def test_trigger_without_header_is_unauthorized(self, client_committing) -> None:
        response = client_committing.post("/runs/trigger")
        assert response.status_code == 401

    def test_trigger_with_wrong_key_is_unauthorized(self, client_committing) -> None:
        response = client_committing.post("/runs/trigger", headers={"X-Admin-Api-Key": "wrong-key"})
        assert response.status_code == 401


class TestTriggerEndpoint:
    def test_trigger_returns_immediately_with_pending_jobs(
        self, client_committing, session_factory: sessionmaker[Session]
    ) -> None:
        """§2.5: 트리거는 CLI 실행을 기다리지 않고 즉시 응답한다 — pending으로 남아있어야 한다."""
        _seed_minimal_dataset(session_factory)

        response = client_committing.post("/runs/trigger", headers=ADMIN_HEADERS)

        assert response.status_code == 200
        body = response.get_json()
        assert body["pending"] == 1
        assert body["running"] == 0
        assert body["success"] == 0

    def test_worker_completes_triggered_batch(
        self, client_committing, session_factory: sessionmaker[Session]
    ) -> None:
        _seed_minimal_dataset(session_factory)
        triggered = client_committing.post("/runs/trigger", headers=ADMIN_HEADERS)
        batch_id = triggered.get_json()["batch_id"]

        _run_worker_to_completion(session_factory, batch_id)

        response = client_committing.get(f"/runs/{batch_id}/status", headers=ADMIN_HEADERS)
        assert response.status_code == 200
        body = response.get_json()
        assert body["success"] == 1
        assert float(body["total_cost_usd"]) > 0

    def test_status_endpoint_404_for_unknown_batch(self, client_committing) -> None:
        response = client_committing.get("/runs/2099-W01/status", headers=ADMIN_HEADERS)
        assert response.status_code == 404


class TestResumeEndpoint:
    def test_resume_unknown_batch_returns_404(self, client_committing) -> None:
        response = client_committing.post("/runs/2099-W01/resume", headers=ADMIN_HEADERS)
        assert response.status_code == 404

    def test_resume_existing_batch_succeeds(
        self, client_committing, session_factory: sessionmaker[Session]
    ) -> None:
        _seed_minimal_dataset(session_factory)
        triggered = client_committing.post("/runs/trigger", headers=ADMIN_HEADERS)
        batch_id = triggered.get_json()["batch_id"]
        _run_worker_to_completion(session_factory, batch_id)

        response = client_committing.post(f"/runs/{batch_id}/resume", headers=ADMIN_HEADERS)

        assert response.status_code == 200
        # 이미 전부 성공했으므로 resume은 재실행할 FAILED 잡이 없다(pending=0 유지).
        assert response.get_json()["pending"] == 0
        assert response.get_json()["success"] == 1
