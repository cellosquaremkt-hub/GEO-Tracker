"""주간 배치 오케스트레이션 — 트리거/재개 API 계층 (worker 데몬과 분리, §2.3).

**이 모듈은 CLI를 절대 실행하지 않는다.** trigger_batch()/resume_batch()는 execution_run을
PENDING 상태로 만들거나 되돌리기만 하고 즉시 반환한다 — 실제 실행(CLI 호출, 파싱, 집계)은
app/worker/daemon.py(별도 프로세스)가 PENDING 잡을 폴링해서 전담한다
(migration_flask_postgres.md §2.3 참조). Flask 라우트(app/api/runs.py)는 이 모듈만 호출하고
app/llm_clients/나 app/worker/daemon.py를 직접 import하지 않는다.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from datetime import UTC, datetime
from decimal import Decimal

from sqlalchemy import func, select, update
from sqlalchemy.orm import Session

from app.core.config import settings
from app.models.enums import ExecutionStatus
from app.models.execution import ExecutionRun
from app.models.llm_provider import LLMProvider
from app.models.prompt import Prompt
from app.services.batch_config_service import get_repeat_count
from app.services.cost_estimate import estimate_batch_calls
from app.services.week_utils import compute_current_week_label

__all__ = [
    "BatchNotFoundError",
    "BatchStatus",
    "BatchTooLargeError",
    "compute_current_week_label",
    "ensure_execution_runs",
    "get_batch_status",
    "resume_batch",
    "trigger_batch",
]

logger = logging.getLogger(__name__)


class BatchNotFoundError(Exception):
    """resume_batch()에 존재하지 않는 batch_id가 주어졌을 때."""


class BatchTooLargeError(Exception):
    """예상 호출 수가 MAX_CALLS_PER_BATCH를 넘어 배치 시작을 거부할 때.

    구독 좌석 rate limit을 실수로 소진하지 않기 위한 안전장치 — trigger_batch에서만 검사한다
    (resume_batch는 이미 생성된 execution_run을 재개하는 것이라 신규 호출량 폭증 위험이 적다).
    """


@dataclass(frozen=True)
class BatchStatus:
    batch_id: str
    pending: int
    running: int
    success: int
    failed: int
    total_cost_usd: Decimal


def ensure_execution_runs(session: Session, batch_id: str) -> int:
    """활성 prompt x 활성 llm_provider x REPEAT_COUNT 조합의 execution_run을 없는 것만 만든다.

    REPEAT_COUNT는 batch_config_service를 통해 얻는다 — 관리자가 Settings 화면에서 저장한 값이
    있으면 그 값을, 없으면 .env(settings.repeat_count)를 쓴다.
    """
    prompt_ids = (
        session.execute(select(Prompt.id).where(Prompt.is_active.is_(True))).scalars().all()
    )
    provider_ids = (
        session.execute(select(LLMProvider.id).where(LLMProvider.is_active.is_(True)))
        .scalars()
        .all()
    )
    existing_keys = set(
        session.execute(
            select(
                ExecutionRun.prompt_id, ExecutionRun.llm_provider_id, ExecutionRun.repeat_index
            ).where(ExecutionRun.batch_id == batch_id)
        ).all()
    )

    repeat_count = get_repeat_count(session)
    now = datetime.now(UTC)
    created = 0
    for prompt_id in prompt_ids:
        for provider_id in provider_ids:
            for repeat_index in range(repeat_count):
                key = (prompt_id, provider_id, repeat_index)
                if key in existing_keys:
                    continue
                session.add(
                    ExecutionRun(
                        batch_id=batch_id,
                        executed_at=now,
                        prompt_id=prompt_id,
                        llm_provider_id=provider_id,
                        repeat_index=repeat_index,
                        status=ExecutionStatus.PENDING,
                    )
                )
                created += 1
    session.commit()
    return created


def get_batch_status(session: Session, batch_id: str) -> BatchStatus:
    rows = session.execute(
        select(ExecutionRun.status, func.count(), func.coalesce(func.sum(ExecutionRun.cost_usd), 0))
        .where(ExecutionRun.batch_id == batch_id)
        .group_by(ExecutionRun.status)
    ).all()
    counts: dict[ExecutionStatus, int] = dict.fromkeys(ExecutionStatus, 0)
    total_cost = Decimal("0")
    for status, count, cost_sum in rows:
        counts[status] = count
        total_cost += Decimal(cost_sum)
    return BatchStatus(
        batch_id=batch_id,
        pending=counts[ExecutionStatus.PENDING],
        running=counts[ExecutionStatus.RUNNING],
        success=counts[ExecutionStatus.SUCCESS],
        failed=counts[ExecutionStatus.FAILED],
        total_cost_usd=total_cost,
    )


def trigger_batch(session: Session) -> BatchStatus:
    """이번 주 배치의 PENDING execution_run을 만들고 즉시 반환한다 (CLI 실행 없음).

    실제 실행은 app/worker/daemon.py가 알아서 집어간다 — 이 함수가 반환한 뒤에도 계속
    pending으로 남아있는 게 정상이며, 프론트엔드는 GET /runs/{batch_id}/status를 폴링해
    진행 상황을 확인한다(§2.5).
    """
    batch_id = compute_current_week_label()
    estimate = estimate_batch_calls(session)
    logger.info(
        "batch_id=%s 트리거 — 예상 호출 %d건 (활성 프롬프트 x 활성 프로바이더 x REPEAT_COUNT). "
        "프로바이더별: %s",
        batch_id,
        estimate.total_calls,
        estimate.per_provider_calls,
    )
    if estimate.total_calls > settings.max_calls_per_batch:
        raise BatchTooLargeError(
            f"batch_id={batch_id}: 예상 호출 {estimate.total_calls}건이 "
            f"MAX_CALLS_PER_BATCH({settings.max_calls_per_batch})를 초과합니다. 구독 좌석 "
            "rate limit 보호를 위해 배치를 시작하지 않습니다. REPEAT_COUNT/활성 프롬프트/"
            "활성 프로바이더 수를 줄이거나 MAX_CALLS_PER_BATCH를 조정하세요."
        )
    created = ensure_execution_runs(session, batch_id)
    logger.info(
        "batch_id=%s: execution_run %d건 PENDING으로 준비 완료(신규 생성분만)", batch_id, created
    )
    return get_batch_status(session, batch_id)


def resume_batch(session: Session, batch_id: str) -> BatchStatus:
    """실패(FAILED)한 execution_run만 PENDING으로 되돌리고 즉시 반환한다 (CLI 실행 없음).

    worker 데몬은 PENDING 상태만 폴링 대상으로 삼는다 — 그래서 재개는 FAILED -> PENDING 전환
    하나로 끝난다. success는 건드리지 않는다(멱등성/재개의 핵심).
    """
    exists = session.execute(
        select(func.count()).select_from(ExecutionRun).where(ExecutionRun.batch_id == batch_id)
    ).scalar_one()
    if exists == 0:
        raise BatchNotFoundError(f"batch_id '{batch_id}'에 해당하는 execution_run이 없습니다.")

    session.execute(
        update(ExecutionRun)
        .where(ExecutionRun.batch_id == batch_id, ExecutionRun.status == ExecutionStatus.FAILED)
        .values(status=ExecutionStatus.PENDING)
    )
    session.commit()
    return get_batch_status(session, batch_id)
