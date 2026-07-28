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
from app.models.enums import BrandType, ExecutionStatus, Priority, Sentiment
from app.models.execution import ExecutionRun, Mention
from app.models.llm_provider import LLMProvider
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

    # brand_type=OWN_BRAND 프롬프트는 "미노출/경쟁사 우위" 판단 대상에서 뺀다 — 브랜드명을
    # 직접 묻는 질문이라 이 두 섹션의 전제(시장 점유율 경쟁 서사)와 맞지 않는다. 이 프롬프트들의
    # 결과는 get_own_brand_answers()의 별도 섹션에서만 확인한다.
    active_prompts = (
        session.execute(
            select(Prompt).where(
                Prompt.is_active.is_(True),
                Prompt.brand_type.is_distinct_from(BrandType.OWN_BRAND),
            )
        )
        .scalars()
        .all()
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


@dataclass(frozen=True)
class OwnBrandAnswer:
    """brand_type=OWN_BRAND 프롬프트 하나의 실행 결과 하나 — SOV 집계에 안 들어가므로 별도로
    "브랜드명을 직접 물었을 때 실제로 그 브랜드를 언급/설명했는가"만 확인하는 품질 체크용이다."""

    execution_run_id: int
    prompt_id: int
    prompt_text: str
    llm_provider_name: str
    repeat_index: int
    own_brand_mentioned: bool
    own_brand_names_mentioned: list[str]
    sentiment: Sentiment | None


def get_own_brand_answers(session: Session, week: str) -> list[OwnBrandAnswer]:
    """brand_type=OWN_BRAND 프롬프트의 이번 주 성공 실행 결과 — weekly_snapshot SOV와는
    완전히 분리된 별도 조회다(aggregation.py에서도 이 브랜드 타입은 제외하고 계산한다)."""
    runs = (
        session.execute(
            select(ExecutionRun, Prompt, LLMProvider)
            .join(Prompt, Prompt.id == ExecutionRun.prompt_id)
            .join(LLMProvider, LLMProvider.id == ExecutionRun.llm_provider_id)
            .where(
                ExecutionRun.batch_id == week,
                ExecutionRun.status == ExecutionStatus.SUCCESS,
                Prompt.brand_type == BrandType.OWN_BRAND,
            )
            .order_by(Prompt.id, ExecutionRun.repeat_index)
        )
        .unique()
        .all()
    )
    if not runs:
        return []

    run_ids = [run.id for run, _, _ in runs]
    own_mentions_by_run: dict[int, list[tuple[str, Sentiment]]] = defaultdict(list)
    for execution_run_id, brand_name, sentiment in session.execute(
        select(Mention.execution_run_id, Brand.name, Mention.sentiment)
        .join(Brand, Brand.id == Mention.brand_id)
        .where(Mention.execution_run_id.in_(run_ids), Brand.is_own.is_(True))
        .order_by(Mention.mention_order)
    ).all():
        own_mentions_by_run[execution_run_id].append((brand_name, sentiment))

    answers: list[OwnBrandAnswer] = []
    for run, prompt, provider in runs:
        own_mentions = own_mentions_by_run.get(run.id, [])
        answers.append(
            OwnBrandAnswer(
                execution_run_id=run.id,
                prompt_id=prompt.id,
                prompt_text=prompt.text,
                llm_provider_name=provider.name,
                repeat_index=run.repeat_index,
                own_brand_mentioned=bool(own_mentions),
                own_brand_names_mentioned=[name for name, _ in own_mentions],
                sentiment=own_mentions[0][1] if own_mentions else None,
            )
        )
    return answers
