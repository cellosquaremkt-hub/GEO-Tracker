from __future__ import annotations

import os
import subprocess
import sys
import threading
import time
from pathlib import Path

import pytest
from sqlalchemy import func, select
from sqlalchemy.orm import Session, sessionmaker

from app.core.config import settings
from app.llm_clients import claude_code_cli_adapter, codex_cli_adapter
from app.llm_clients.base import LLMResponse
from app.llm_clients.cli_common import CLIProcessError, CLITimeoutError
from app.models.brand import Brand, BrandAlias, BrandDomain
from app.models.enums import ExecutionStatus, Language, Priority, Target
from app.models.execution import Citation, ExecutionRun, Mention
from app.models.llm_provider import LLMProvider
from app.models.prompt import Prompt
from app.models.snapshot import WeeklySnapshot
from app.services.aggregation import aggregate_week
from app.services.batch_runner import (
    BatchNotFoundError,
    BatchTooLargeError,
    compute_current_week_label,
    ensure_execution_runs,
    get_batch_status,
    resume_batch,
    trigger_batch,
)
from app.worker.daemon import WeeklyBatchWorker

pytestmark = pytest.mark.usefixtures("clean_batch_tables")

_BACKEND_DIR = Path(__file__).resolve().parents[1]


def _seed_minimal_dataset(session_factory: sessionmaker[Session]) -> None:
    with session_factory() as session:
        own_brand = Brand(name="삼성SDS", is_own=True)
        competitor = Brand(name="LX Pantos", is_own=False)
        session.add_all([own_brand, competitor])
        session.flush()
        session.add_all(
            [
                BrandAlias(brand_id=own_brand.id, alias_text="Samsung SDS"),
                BrandDomain(brand_id=own_brand.id, domain="samsungsds.com"),
                BrandDomain(brand_id=own_brand.id, domain="cellosquare.com"),
                BrandDomain(brand_id=competitor.id, domain="lxpantos.com"),
            ]
        )
        session.add_all(
            [
                LLMProvider(
                    name="claude-code-cli", model_string="sonnet", supports_web_search=True
                ),
                LLMProvider(name="codex-cli", model_string="gpt-5.5", supports_web_search=True),
            ]
        )
        session.add_all(
            [
                Prompt(
                    text="국내 디지털 포워딩 플랫폼을 추천해줘.",
                    intent="Test",
                    target=Target.MANAGER,
                    priority=Priority.HIGH,
                    language=Language.KO,
                ),
                Prompt(
                    text="Compare enterprise freight forwarding platforms.",
                    intent="Test",
                    target=Target.MANAGER,
                    priority=Priority.MEDIUM,
                    language=Language.EN,
                ),
            ]
        )
        session.commit()


@pytest.fixture(autouse=True)
def _fast_batch_settings(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(settings, "mock_llm", True)
    monkeypatch.setattr(settings, "repeat_count", 1)
    monkeypatch.setattr(settings, "claude_code_concurrency_limit", 4)
    monkeypatch.setattr(settings, "codex_concurrency_limit", 4)
    monkeypatch.setattr(settings, "gemini_cli_concurrency_limit", 4)


def _run_worker_to_completion(
    session_factory: sessionmaker[Session], batch_id: str, timeout: float = 5.0
):
    """worker.poll_once()를 pending/running이 모두 0이 될 때까지 반복 호출한다 (테스트 전용 —
    실제 데몬은 run_forever()로 이 폴링을 상시 반복한다)."""
    worker = WeeklyBatchWorker(session_factory)
    deadline = time.monotonic() + timeout
    try:
        while time.monotonic() < deadline:
            worker.poll_once()
            with session_factory() as session:
                status = get_batch_status(session, batch_id)
            if status.pending == 0 and status.running == 0:
                worker.poll_once()  # 집계(aggregate)까지 한 번 더 확실히 돌게 한다
                return status
            time.sleep(0.05)
    finally:
        worker.shutdown()
    raise AssertionError(f"batch_id={batch_id} 처리가 {timeout}초 안에 끝나지 않았습니다.")


class TestTriggerBatchReturnsImmediately:
    """§2.3 분리 원칙의 가장 직접적인 검증 — trigger_batch()는 CLI를 절대 호출하지 않는다."""

    def test_trigger_batch_never_touches_subprocess(
        self, session_factory: sessionmaker[Session], monkeypatch: pytest.MonkeyPatch
    ) -> None:
        _seed_minimal_dataset(session_factory)

        def _boom(*_args: object, **_kwargs: object) -> None:
            raise AssertionError(
                "trigger_batch()가 subprocess를 실행하려 했다 (§2.3 분리 원칙 위반)"
            )

        monkeypatch.setattr(subprocess, "Popen", _boom)
        monkeypatch.setattr(settings, "mock_llm", False)

        with session_factory() as session:
            status = trigger_batch(session)

        # 2 prompts x 2 providers x repeat_count(1) = 4건, 전부 PENDING 상태로만 남아있어야 한다.
        assert status.pending == 4
        assert status.running == 0
        assert status.success == 0
        assert status.failed == 0


class TestTriggerBatchEndToEnd:
    def test_seed_trigger_worker_aggregate(self, session_factory: sessionmaker[Session]) -> None:
        _seed_minimal_dataset(session_factory)

        with session_factory() as session:
            triggered = trigger_batch(session)
        assert triggered.pending == 4

        status = _run_worker_to_completion(session_factory, triggered.batch_id)

        assert status.pending == 0
        assert status.running == 0
        assert status.success == 4
        assert status.failed == 0
        assert status.total_cost_usd > 0

        with session_factory() as session:
            runs = (
                session.execute(
                    select(ExecutionRun).where(ExecutionRun.batch_id == status.batch_id)
                )
                .scalars()
                .all()
            )
            assert len(runs) == 4
            assert all(r.status == ExecutionStatus.SUCCESS for r in runs)
            assert all(r.raw_response for r in runs)
            # codex-cli는 실제로도 토큰 수/비용을 신뢰성 있게 못 뽑아 항상 None이다
            # (app/llm_clients/codex_cli_adapter.py, mock.py의 _CLI_TOKENS_UNAVAILABLE 참조) —
            # claude-code-cli 쪽만 토큰/비용이 채워지는지 확인한다.
            assert any(r.input_tokens and r.output_tokens and r.cost_usd is not None for r in runs)

            mention_count = session.execute(select(func.count()).select_from(Mention)).scalar_one()
            assert mention_count > 0

            citation_count = session.execute(
                select(func.count()).select_from(Citation)
            ).scalar_one()
            assert citation_count > 0

            snapshots = (
                session.execute(
                    select(WeeklySnapshot).where(WeeklySnapshot.week_label == status.batch_id)
                )
                .scalars()
                .all()
            )
            # 브랜드 2개 x (전체합산 1 + 활성 프로바이더 2) = 6개 스냅샷.
            assert len(snapshots) == 6
            all_provider_snapshots = [s for s in snapshots if s.llm_provider_id is None]
            assert len(all_provider_snapshots) == 2
            assert all(s.total_runs == 4 for s in all_provider_snapshots)

    def test_retriggering_same_week_is_idempotent(
        self, session_factory: sessionmaker[Session]
    ) -> None:
        _seed_minimal_dataset(session_factory)

        with session_factory() as session:
            first = trigger_batch(session)
        with session_factory() as session:
            second = trigger_batch(session)

        assert first.batch_id == second.batch_id
        assert second.pending == 4  # 재트리거해도 execution_run이 중복 생성되지 않는다.

        with session_factory() as session:
            total_runs = session.execute(
                select(func.count())
                .select_from(ExecutionRun)
                .where(ExecutionRun.batch_id == first.batch_id)
            ).scalar_one()
            assert total_runs == 4


class TestResumeAfterFailure:
    def test_failed_job_is_retried_and_snapshot_updates(
        self, session_factory: sessionmaker[Session], monkeypatch: pytest.MonkeyPatch
    ) -> None:
        _seed_minimal_dataset(session_factory)

        call_count = 0
        real_query = claude_code_cli_adapter.ClaudeCodeCLIAdapter.query

        def _flaky_query(
            self: claude_code_cli_adapter.ClaudeCodeCLIAdapter, prompt: str
        ) -> LLMResponse:
            nonlocal call_count
            call_count += 1
            if call_count == 1:
                raise RuntimeError("일시적인 네트워크 오류(테스트 주입)")
            return real_query(self, prompt)

        monkeypatch.setattr(claude_code_cli_adapter.ClaudeCodeCLIAdapter, "query", _flaky_query)

        with session_factory() as session:
            triggered = trigger_batch(session)
        first_status = _run_worker_to_completion(session_factory, triggered.batch_id)

        assert first_status.failed == 1
        assert first_status.success == 3
        call_count_after_first = call_count

        with session_factory() as session:
            first_snapshot = (
                session.execute(
                    select(WeeklySnapshot).where(
                        WeeklySnapshot.week_label == first_status.batch_id,
                        WeeklySnapshot.llm_provider_id.is_(None),
                    )
                )
                .scalars()
                .first()
            )
            assert first_snapshot is not None
            assert first_snapshot.total_runs == 3  # 실패 run은 분모에서 제외된다.

            failed_run = session.execute(
                select(ExecutionRun).where(
                    ExecutionRun.batch_id == first_status.batch_id,
                    ExecutionRun.status == ExecutionStatus.FAILED,
                )
            ).scalar_one()
            assert "RuntimeError" in (failed_run.error_message or "")

        with session_factory() as session:
            resumed = resume_batch(session, first_status.batch_id)
        assert resumed.pending == 1  # 실패했던 잡 1건만 PENDING으로 되돌아간다.

        second_status = _run_worker_to_completion(session_factory, first_status.batch_id)
        assert second_status.failed == 0
        assert second_status.success == 4
        assert call_count == call_count_after_first + 1  # 실패했던 잡 1건만 재실행됨.

        with session_factory() as session:
            second_snapshot = (
                session.execute(
                    select(WeeklySnapshot).where(
                        WeeklySnapshot.week_label == first_status.batch_id,
                        WeeklySnapshot.llm_provider_id.is_(None),
                    )
                )
                .scalars()
                .first()
            )
            assert second_snapshot is not None
            assert second_snapshot.total_runs == 4  # 재집계 후 분모가 4로 늘어난다.

    def test_resume_unknown_batch_id_raises(self, session_factory: sessionmaker[Session]) -> None:
        with session_factory() as session, pytest.raises(BatchNotFoundError):
            resume_batch(session, "2099-W01")


class TestEnsureExecutionRuns:
    def test_creates_expected_combinations(self, session_factory: sessionmaker[Session]) -> None:
        _seed_minimal_dataset(session_factory)
        batch_id = compute_current_week_label()

        with session_factory() as session:
            created = ensure_execution_runs(session, batch_id)
        assert created == 4  # 2 prompts x 2 providers x repeat_count(1)

        with session_factory() as session:
            created_again = ensure_execution_runs(session, batch_id)
        assert created_again == 0  # 이미 존재하므로 추가 생성 없음.


class TestBatchTooLarge:
    def test_trigger_rejects_batch_exceeding_max_calls(
        self, session_factory: sessionmaker[Session], monkeypatch: pytest.MonkeyPatch
    ) -> None:
        _seed_minimal_dataset(session_factory)
        monkeypatch.setattr(settings, "max_calls_per_batch", 3)

        with session_factory() as session, pytest.raises(BatchTooLargeError):
            trigger_batch(session)

        with session_factory() as session:
            total_runs = session.execute(
                select(func.count()).select_from(ExecutionRun)
            ).scalar_one()
            assert total_runs == 0


class TestReaggregationUpsert:
    def test_reaggregating_same_week_does_not_duplicate_snapshot_rows(
        self, session_factory: sessionmaker[Session]
    ) -> None:
        _seed_minimal_dataset(session_factory)
        with session_factory() as session:
            triggered = trigger_batch(session)
        status = _run_worker_to_completion(session_factory, triggered.batch_id)

        with session_factory() as session:
            first_count = session.execute(
                select(func.count())
                .select_from(WeeklySnapshot)
                .where(WeeklySnapshot.week_label == status.batch_id)
            ).scalar_one()

        with session_factory() as session:
            aggregate_week(session, status.batch_id)
            aggregate_week(session, status.batch_id)

        with session_factory() as session:
            second_count = session.execute(
                select(func.count())
                .select_from(WeeklySnapshot)
                .where(WeeklySnapshot.week_label == status.batch_id)
            ).scalar_one()

        assert first_count == 6
        assert second_count == first_count


class TestCliFailureIsolation:
    """CLI 프로세스 타임아웃/비정상 종료가 error_message에 기록되고 배치가 계속 진행되는지 확인."""

    def test_timeout_and_process_error_recorded_batch_continues(
        self, session_factory: sessionmaker[Session], monkeypatch: pytest.MonkeyPatch
    ) -> None:
        _seed_minimal_dataset(session_factory)

        def _claude_times_out(self: object, prompt: str) -> LLMResponse:
            raise CLITimeoutError("claude-code-cli: 180초 안에 응답하지 않아 종료했습니다.")

        def _codex_process_error(self: object, prompt: str) -> LLMResponse:
            raise CLIProcessError("codex-cli: 종료 코드 1. stderr: boom")

        monkeypatch.setattr(
            claude_code_cli_adapter.ClaudeCodeCLIAdapter, "query", _claude_times_out
        )
        monkeypatch.setattr(codex_cli_adapter.CodexCLIAdapter, "query", _codex_process_error)

        with session_factory() as session:
            triggered = trigger_batch(session)
        status = _run_worker_to_completion(session_factory, triggered.batch_id)

        # 2 prompts x 2 providers x repeat_count(1) = 4건, 전부 실패하지만 배치 자체는 끝까지
        # 돌아야 한다(한 잡의 실패가 다른 잡들을 죽이지 않는지 확인).
        assert status.pending == 0
        assert status.running == 0
        assert status.success == 0
        assert status.failed == 4

        with session_factory() as session:
            failed_runs = (
                session.execute(
                    select(ExecutionRun).where(ExecutionRun.batch_id == status.batch_id)
                )
                .scalars()
                .all()
            )
            assert len(failed_runs) == 4
            assert all(r.status == ExecutionStatus.FAILED for r in failed_runs)
            messages = {r.error_message for r in failed_runs}
            assert any("CLITimeoutError" in m for m in messages if m)
            assert any("CLIProcessError" in m for m in messages if m)


class TestConcurrencyLimitEnforced:
    """프로바이더별 동시 실행 수가 설정한 상한을 절대 넘지 않는지 실측한다."""

    def test_provider_concurrency_never_exceeds_limit(
        self, session_factory: sessionmaker[Session], monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setattr(settings, "claude_code_concurrency_limit", 2)

        with session_factory() as session:
            brand = Brand(name="삼성SDS", is_own=True)
            session.add(brand)
            session.add(
                LLMProvider(name="claude-code-cli", model_string="sonnet", supports_web_search=True)
            )
            for i in range(6):
                session.add(
                    Prompt(
                        text=f"동시성 테스트 프롬프트 {i}",
                        intent="Test",
                        target=Target.MANAGER,
                        priority=Priority.LOW,
                        language=Language.KO,
                    )
                )
            session.commit()

        with session_factory() as session:
            triggered = trigger_batch(session)
        assert triggered.pending == 6

        lock = threading.Lock()
        current = 0
        max_seen = 0

        def _slow_query(self: object, prompt: str) -> LLMResponse:
            nonlocal current, max_seen
            with lock:
                current += 1
                max_seen = max(max_seen, current)
            time.sleep(0.1)
            with lock:
                current -= 1
            return LLMResponse(text="ok", citations=[], web_search_used=True)

        monkeypatch.setattr(claude_code_cli_adapter.ClaudeCodeCLIAdapter, "query", _slow_query)

        status = _run_worker_to_completion(session_factory, triggered.batch_id, timeout=10.0)
        assert status.success == 6
        assert max_seen <= 2


class TestWorkerDaemonSeparateProcess:
    """worker 데몬을 실제 별도 프로세스로 띄워 PENDING 잡을 집어가 처리하는지 확인한다."""

    def test_daemon_process_picks_up_pending_jobs(
        self, session_factory: sessionmaker[Session]
    ) -> None:
        _seed_minimal_dataset(session_factory)
        with session_factory() as session:
            triggered = trigger_batch(session)
        assert triggered.pending == 4

        env = os.environ.copy()
        env["DATABASE_URL"] = settings.test_database_url or ""
        env["MOCK_LLM"] = "true"
        env["WORKER_POLL_INTERVAL_SEC"] = "0.2"

        proc = subprocess.Popen(
            [sys.executable, "-m", "app.worker.daemon"],
            cwd=str(_BACKEND_DIR),
            env=env,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
        )
        final_status = None
        try:
            deadline = time.monotonic() + 15.0
            while time.monotonic() < deadline:
                with session_factory() as session:
                    final_status = get_batch_status(session, triggered.batch_id)
                if final_status.pending == 0 and final_status.running == 0:
                    break
                time.sleep(0.3)
        finally:
            proc.terminate()
            try:
                proc.wait(timeout=5)
            except subprocess.TimeoutExpired:
                proc.kill()
                proc.wait(timeout=5)

        assert final_status is not None
        assert final_status.pending == 0
        assert final_status.running == 0
        assert final_status.success + final_status.failed == 4
