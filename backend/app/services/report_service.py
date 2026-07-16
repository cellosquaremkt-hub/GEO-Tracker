"""주간 리포트 — 요약 + 취약 키워드 우선순위 + 경쟁사 우위 프롬프트.

"취약"은 (a) 우리 브랜드가 이번 주 그 프롬프트의 성공 실행에서 전혀 언급되지 않았거나,
(b) 언급은 됐지만 전부 부정적일 때로 정의한다. "경쟁사 우위"는 경쟁사의 최고(가장 낮은=이른)
평균 mention_order가 우리 브랜드의 평균보다 낮거나, 우리 브랜드가 아예 언급되지 않았을 때로
정의한다 — mention_order는 rank의 근사치일 뿐이라는 한계는 docs/metrics.md 참조.
"""

from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass
from decimal import Decimal

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.models.brand import Brand
from app.models.enums import ExecutionStatus, Priority, Sentiment
from app.models.execution import ExecutionRun, Mention
from app.models.prompt import Prompt
from app.services.dashboard_service import compute_own_sov_sum

_PRIORITY_ORDER = {Priority.HIGH: 0, Priority.MEDIUM: 1, Priority.LOW: 2}


@dataclass(frozen=True)
class WeeklyReportSummary:
    week: str
    total_execution_runs: int
    success_count: int
    failed_count: int
    own_total_sov: Decimal


@dataclass(frozen=True)
class VulnerablePrompt:
    prompt_id: int
    prompt_text: str
    intent: str
    priority: Priority
    reason: str


@dataclass(frozen=True)
class CompetitorAdvantagePrompt:
    prompt_id: int
    prompt_text: str
    own_avg_rank: Decimal | None
    leading_competitor_id: int
    leading_competitor_name: str
    leading_competitor_avg_rank: Decimal


@dataclass(frozen=True)
class WeeklyReport:
    summary: WeeklyReportSummary
    vulnerable_prompts: list[VulnerablePrompt]
    competitor_advantage_prompts: list[CompetitorAdvantagePrompt]


def compute_weekly_report(session: Session, week: str) -> WeeklyReport:
    status_counts: dict[ExecutionStatus, int] = dict(
        session.execute(
            select(ExecutionRun.status, func.count())
            .where(ExecutionRun.batch_id == week)
            .group_by(ExecutionRun.status)
        ).all()
    )
    success_count = status_counts.get(ExecutionStatus.SUCCESS, 0)
    failed_count = status_counts.get(ExecutionStatus.FAILED, 0)
    total_execution_runs = sum(status_counts.values())

    own_brand_ids = list(
        session.execute(select(Brand.id).where(Brand.is_own.is_(True))).scalars().all()
    )
    own_total_sov = compute_own_sov_sum(session, week, own_brand_ids) or Decimal("0")

    active_prompts = (
        session.execute(select(Prompt).where(Prompt.is_active.is_(True))).scalars().all()
    )

    mention_rows = session.execute(
        select(
            ExecutionRun.prompt_id,
            Mention.brand_id,
            Brand.is_own,
            Brand.name,
            Mention.mention_order,
            Mention.sentiment,
        )
        .select_from(Mention)
        .join(ExecutionRun, ExecutionRun.id == Mention.execution_run_id)
        .join(Brand, Brand.id == Mention.brand_id)
        .where(ExecutionRun.batch_id == week, ExecutionRun.status == ExecutionStatus.SUCCESS)
    ).all()

    by_prompt: dict[int, list[tuple[int, bool, str, int, Sentiment]]] = defaultdict(list)
    for prompt_id, brand_id, is_own, brand_name, mention_order, sentiment in mention_rows:
        by_prompt[prompt_id].append((brand_id, is_own, brand_name, mention_order, sentiment))

    prompts_with_runs: set[int] = set(
        session.execute(
            select(ExecutionRun.prompt_id.distinct()).where(
                ExecutionRun.batch_id == week, ExecutionRun.status == ExecutionStatus.SUCCESS
            )
        )
        .scalars()
        .all()
    )

    vulnerable: list[VulnerablePrompt] = []
    competitor_advantage: list[CompetitorAdvantagePrompt] = []

    for prompt in active_prompts:
        if prompt.id not in prompts_with_runs:
            continue  # 이번 주 실행이 아직 없으면 판단을 보류한다(아직 실측 안 됨과 취약을 구분).

        entries = by_prompt.get(prompt.id, [])
        own_entries = [e for e in entries if e[1]]
        competitor_entries = [e for e in entries if not e[1]]

        if not own_entries:
            vulnerable.append(
                VulnerablePrompt(prompt.id, prompt.text, prompt.intent, prompt.priority, "미노출")
            )
        elif all(e[4] == Sentiment.NEGATIVE for e in own_entries):
            vulnerable.append(
                VulnerablePrompt(
                    prompt.id, prompt.text, prompt.intent, prompt.priority, "부정적 언급만 존재"
                )
            )

        own_avg_rank = (
            Decimal(sum(e[3] for e in own_entries)) / Decimal(len(own_entries))
            if own_entries
            else None
        )

        competitor_groups: dict[int, list[tuple[int, bool, str, int, Sentiment]]] = defaultdict(
            list
        )
        for e in competitor_entries:
            competitor_groups[e[0]].append(e)

        best_competitor: tuple[int, str, Decimal] | None = None
        for brand_id, group in competitor_groups.items():
            avg_rank = Decimal(sum(x[3] for x in group)) / Decimal(len(group))
            if best_competitor is None or avg_rank < best_competitor[2]:
                best_competitor = (brand_id, group[0][2], avg_rank)

        if best_competitor is not None and (
            own_avg_rank is None or best_competitor[2] < own_avg_rank
        ):
            competitor_advantage.append(
                CompetitorAdvantagePrompt(
                    prompt_id=prompt.id,
                    prompt_text=prompt.text,
                    own_avg_rank=own_avg_rank,
                    leading_competitor_id=best_competitor[0],
                    leading_competitor_name=best_competitor[1],
                    leading_competitor_avg_rank=best_competitor[2],
                )
            )

    vulnerable.sort(key=lambda v: (_PRIORITY_ORDER[v.priority], v.prompt_id))
    competitor_advantage.sort(key=lambda c: c.prompt_id)

    summary = WeeklyReportSummary(
        week=week,
        total_execution_runs=total_execution_runs,
        success_count=success_count,
        failed_count=failed_count,
        own_total_sov=own_total_sov,
    )
    return WeeklyReport(
        summary=summary,
        vulnerable_prompts=vulnerable,
        competitor_advantage_prompts=competitor_advantage,
    )
