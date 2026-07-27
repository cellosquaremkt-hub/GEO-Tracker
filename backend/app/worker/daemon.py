"""주간 배치 실행 전용 worker 데몬 — 이 프로젝트에서 CLI 서브프로세스를 실행하는 유일한 프로세스.

실행: python -m app.worker.daemon  (운영에서는 systemd 유닛으로 상시 실행, Restart=on-failure)

Flask 웹 앱(app/main.py, Gunicorn)은 이 프로세스와 완전히 분리되어 있다 — 웹 앱은 execution_run을
PENDING으로 만들기만 하고(app/services/batch_runner.py), 실제 CLI 호출/파싱/집계는 전부 이
프로세스가 한다(migration_flask_postgres.md §2.3). **정확히 1개 인스턴스만 떠 있어야 한다**
(systemd가 보장 — Phase 7). 여러 인스턴스가 동시에 뜨면 같은 PENDING 잡을 중복 실행할 수 있다.

WeeklyBatchWorker는 session_factory를 주입받는다(참고 프로젝트의 async 버전과 동일한 이유 —
services/는 트리거 계층에 의존하지 않아야 하고, 테스트가 프로덕션 DB 대신 테스트 DB에 바인딩된
팩토리를 넘길 수 있어야 한다). main()에서만 실제 app.db.session.SessionLocal을 기본값으로 쓴다.
"""

from __future__ import annotations

import logging
import signal
import time
from concurrent.futures import ThreadPoolExecutor
from datetime import UTC, datetime

from sqlalchemy import delete, select, update
from sqlalchemy.orm import Session, selectinload, sessionmaker

from app.core.config import settings
from app.db.session import SessionLocal
from app.llm_clients.factory import get_adapter
from app.models.enums import ExecutionStatus
from app.models.execution import Citation, ExecutionRun, Mention
from app.models.llm_provider import LLMProvider
from app.services.aggregation import aggregate_week
from app.services.batch_runner import get_batch_status
from app.services.brand_loader import load_brand_infos
from app.services.response_parser import BrandInfo, ExecutionRunInput, parse_response
from app.services.sentiment import SentimentClassifier, get_default_sentiment_classifier

logger = logging.getLogger(__name__)

_CONCURRENCY_BY_PROVIDER_NAME: dict[str, int] = {
    "claude-code-cli": settings.claude_code_concurrency_limit,
    "codex-cli": settings.codex_concurrency_limit,
    "gemini-cli": settings.gemini_cli_concurrency_limit,
}


def _run_single_execution(
    session_factory: sessionmaker[Session],
    run_id: int,
    brands: list[BrandInfo],
    sentiment_classifier: SentimentClassifier,
) -> None:
    """이미 RUNNING으로 표시된 execution_run 하나를 실행하고 결과를 저장한다.

    ThreadPoolExecutor 워커 스레드 안에서 실행된다 — 이 함수 하나가 자기 세션을 열고 닫는다
    (SQLAlchemy Session은 스레드 간 공유 불가).
    """
    session = session_factory()
    try:
        run = session.get(
            ExecutionRun,
            run_id,
            options=[selectinload(ExecutionRun.llm_provider), selectinload(ExecutionRun.prompt)],
        )
        if run is None:
            return

        try:
            adapter = get_adapter(run.llm_provider.name, model=run.llm_provider.model_string)
            response = adapter.query(run.prompt.text)

            run.raw_response = response.text
            run.input_tokens = response.input_tokens
            run.output_tokens = response.output_tokens
            run.cost_usd = response.cost_usd

            exec_input = ExecutionRunInput(
                raw_response=response.text, adapter_citations=tuple(response.citations)
            )
            parsed = parse_response(exec_input, brands, sentiment_classifier=sentiment_classifier)

            # 재개(resume) 시 이전 시도의 mention/citation이 남아있을 수 있어 먼저 지운다.
            session.execute(delete(Mention).where(Mention.execution_run_id == run.id))
            session.execute(delete(Citation).where(Citation.execution_run_id == run.id))
            for m in parsed.mentions:
                session.add(
                    Mention(
                        execution_run_id=run.id,
                        brand_id=m.brand_id,
                        mention_order=m.mention_order,
                        sentiment=m.sentiment,
                        sentiment_evidence=m.sentiment_evidence,
                    )
                )
            for c in parsed.citations:
                session.add(
                    Citation(
                        execution_run_id=run.id,
                        url=c.url,
                        domain=c.domain,
                        matched_brand_id=c.matched_brand_id,
                    )
                )

            run.status = ExecutionStatus.SUCCESS
            run.error_message = None
        except Exception as exc:  # 잡 하나의 실패가 배치 전체를 막지 않도록 격리한다.
            run.status = ExecutionStatus.FAILED
            run.error_message = f"{type(exc).__name__}: {exc}"[:2000]
            logger.warning("execution_run %s 실패: %s", run.id, run.error_message)
        finally:
            run.executed_at = datetime.now(UTC)
            session.commit()
    finally:
        session.close()


class WeeklyBatchWorker:
    """PENDING execution_run을 폴링해서 실행하는 상주 루프. 정확히 1개 인스턴스만 떠야 한다."""

    def __init__(self, session_factory: sessionmaker[Session] = SessionLocal) -> None:
        self._session_factory = session_factory
        self._executors: dict[str, ThreadPoolExecutor] = {
            name: ThreadPoolExecutor(max_workers=limit, thread_name_prefix=f"cli-{name}")
            for name, limit in _CONCURRENCY_BY_PROVIDER_NAME.items()
        }
        self._last_aggregated_done_count: dict[str, int] = {}
        self._running = True

    def stop(self, *_args: object) -> None:
        self._running = False

    def shutdown(self) -> None:
        for executor in self._executors.values():
            executor.shutdown(wait=True)

    def run_forever(self) -> None:
        self.recover_stuck_running_jobs()
        logger.info("worker daemon 시작 — poll_interval=%.1fs", settings.worker_poll_interval_sec)
        while self._running:
            try:
                self.poll_once()
            except Exception:
                logger.exception("poll 루프에서 처리되지 않은 예외 발생 — 다음 폴링에서 계속한다")
            time.sleep(settings.worker_poll_interval_sec)
        self.shutdown()

    def recover_stuck_running_jobs(self) -> int:
        """이전 실행이 비정상 종료(kill -9, 서버 재부팅 등)해 RUNNING으로 남은 잡을 PENDING으로
        되돌린다. 데몬 시작 시 한 번 호출한다(§5 "재개 동작" 검증 포인트)."""
        session = self._session_factory()
        try:
            result = session.execute(
                update(ExecutionRun)
                .where(ExecutionRun.status == ExecutionStatus.RUNNING)
                .values(status=ExecutionStatus.PENDING)
            )
            session.commit()
            if result.rowcount:
                logger.warning(
                    "이전 비정상 종료로 RUNNING에 남아있던 잡 %d건을 PENDING으로 되돌렸습니다.",
                    result.rowcount,
                )
            return result.rowcount
        finally:
            session.close()

    def poll_once(self) -> int:
        """PENDING 잡을 가져가 RUNNING으로 표시하고 각자의 ThreadPoolExecutor에 제출한다.

        제출만 하고 완료를 기다리지 않는다(non-blocking) — 반환값은 이번 폴링에서 새로 제출한
        잡 수다.

        migration_flask_postgres.md §Phase 4는 동시 pickup 안전장치로 `SELECT ... FOR UPDATE
        SKIP LOCKED` 활용을 "검토"하도록 제안했다 — 이 클래스가 정확히 1개 인스턴스만 떠야
        한다는 전제(클래스 docstring 참조, systemd가 보장)가 이미 "같은 PENDING 잡을 두 곳에서
        동시에 집어가는" 경쟁 상황 자체를 구조적으로 없애므로, 여기서는 평범한 SELECT+UPDATE로
        충분하다고 판단했다 — 여러 인스턴스가 뜰 수 있는 아키텍처로 바뀌면(예: docs/backlog.md의
        Celery+Redis 전환) 그때 `SKIP LOCKED`를 다시 검토해야 한다.
        """
        session = self._session_factory()
        try:
            rows = session.execute(
                select(ExecutionRun.id, LLMProvider.name)
                .join(LLMProvider, LLMProvider.id == ExecutionRun.llm_provider_id)
                .where(ExecutionRun.status == ExecutionStatus.PENDING)
            ).all()
            if rows:
                run_ids = [run_id for run_id, _ in rows]
                session.execute(
                    update(ExecutionRun)
                    .where(ExecutionRun.id.in_(run_ids))
                    .values(status=ExecutionStatus.RUNNING)
                )
                session.commit()
                brands = load_brand_infos(session)
        finally:
            session.close()

        # 잡 제출을 집계보다 먼저 한다 — 집계(_aggregate_completed_batches)에서 예외가 나도
        # 이미 RUNNING으로 표시해 커밋한 잡들은 반드시 실행에 제출되어야 한다. 순서가 바뀌면
        # (집계 실패 → 예외 전파 → 아래 제출 코드가 아예 실행 안 됨) RUNNING으로 표시된 채
        # 영원히 멈춘 잡이 남는다 — 2026-07-16 실측으로 이 실패 모드를 직접 확인했다(테스트용
        # batch_id가 weekly_snapshot.week_label 컬럼 길이 제한을 넘겨 매 폴링마다 집계가
        # 예외를 던졌고, 그 뒤에 있던 새 잡 제출 코드가 계속 실행되지 못해 새로 트리거한 배치
        # 전체가 RUNNING 상태로 멈춰 있었다).
        if rows:
            sentiment_classifier = get_default_sentiment_classifier()
            for run_id, provider_name in rows:
                executor = self._executors.get(provider_name)
                if executor is None:
                    logger.error(
                        "알 수 없는 프로바이더 '%s' (run_id=%d) — 실행하지 않습니다.",
                        provider_name,
                        run_id,
                    )
                    continue
                executor.submit(
                    _run_single_execution,
                    self._session_factory,
                    run_id,
                    brands,
                    sentiment_classifier,
                )

        # 새로 제출할 잡이 있는지와 무관하게 매 폴링마다 확인한다 — 다른 배치가 이번 폴링
        # 직전에 완료됐을 수 있기 때문이다. 이 호출 자체가 실패해도(위 주석 참조) 위의 잡
        # 제출에는 이미 영향을 줄 수 없다 — 그래도 다음 폴링을 계속 이어가기 위해 감싼다.
        agg_session = self._session_factory()
        try:
            self._aggregate_completed_batches(agg_session)
        except Exception:
            logger.exception("배치 집계 중 예외 발생 — 다음 폴링에서 계속 시도한다")
        finally:
            agg_session.close()

        return len(rows)

    def _aggregate_completed_batches(self, session: Session) -> None:
        """모든 execution_run이 SUCCESS/FAILED로 끝난 배치를 찾아 재집계한다.

        DB 상태(성공+실패 수)를 시그니처로 써서, 직전 집계 이후 변화가 없으면 다시 계산하지
        않는다 — daemon 재시작 후에도(메모리 캐시가 비어도) 안전하게 동작한다: 재시작 직후엔
        모든 완료 배치가 "아직 집계 안 됨"으로 취급되어 한 번 더 집계될 뿐, 결과는 delete+insert라
        멱등적이다.

        배치 하나의 집계 실패가 다른 배치의 집계를 막지 않도록 각각 독립적으로 시도한다 —
        실패한 배치는 다음 폴링에서 다시 시도된다(단, 원인이 데이터 자체의 문제라면 사람이
        고칠 때까지 계속 실패로 로그만 쌓인다 — 무한 재시도 자체를 막지는 않는다).
        """
        pending_or_running = (
            select(ExecutionRun.batch_id)
            .where(ExecutionRun.status.in_([ExecutionStatus.PENDING, ExecutionStatus.RUNNING]))
            .distinct()
        )
        all_batches = select(ExecutionRun.batch_id).distinct()
        completed_batch_ids = (
            session.execute(all_batches.except_(pending_or_running)).scalars().all()
        )

        for batch_id in completed_batch_ids:
            status = get_batch_status(session, batch_id)
            done_count = status.success + status.failed
            if self._last_aggregated_done_count.get(batch_id) == done_count:
                continue
            try:
                aggregate_week(session, batch_id)
            except Exception:
                session.rollback()  # 실패한 트랜잭션을 정리해야 다음 batch_id 처리를 계속할 수 있다
                logger.exception("batch_id=%s 집계 실패 — 다른 배치 집계는 계속 진행한다", batch_id)
                continue
            self._last_aggregated_done_count[batch_id] = done_count
            logger.info(
                "batch_id=%s 집계 완료: success=%d failed=%d",
                batch_id,
                status.success,
                status.failed,
            )


def main() -> None:
    logging.basicConfig(level=settings.log_level)
    worker = WeeklyBatchWorker()
    signal.signal(signal.SIGTERM, worker.stop)
    signal.signal(signal.SIGINT, worker.stop)
    worker.run_forever()


if __name__ == "__main__":
    main()
