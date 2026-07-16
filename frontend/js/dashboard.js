// 대시보드 뷰 — GET /dashboard/summary, /trends, /brands/{id}/overview, /prompts 조합.
import * as api from "./api.js";
import { ApiError } from "./api.js";
import { renderEmpty, renderError, renderLoading, showToast } from "./ui.js";
import { applyDelta, escapeHtml, formatPercent, toNumber } from "./format.js";
import { providerDisplayName } from "./providers.js";
import { renderTrendChart } from "./charts.js";
import { loadWeekMentions, clearWeekDataCache } from "./weekData.js";

const state = {
  selectedBrandId: null,
  trends: null,
};

let originalDashboardHtml = null;

function view() {
  const el = document.querySelector("#view-dashboard");
  if (originalDashboardHtml === null) originalDashboardHtml = el.innerHTML;
  return el;
}

function ensureSkeleton() {
  const el = view();
  if (!document.querySelector("#statSov")) {
    el.innerHTML = originalDashboardHtml;
  }
}

function els() {
  return {
    batchStatusBanner: document.querySelector("#batchStatusBanner"),
    statSov: document.querySelector("#statSov"),
    statSovDelta: document.querySelector("#statSovDelta"),
    statRank: document.querySelector("#statRank"),
    statRankDelta: document.querySelector("#statRankDelta"),
    statPrompts: document.querySelector("#statPrompts"),
    statNegative: document.querySelector("#statNegative"),
    statNegativeDelta: document.querySelector("#statNegativeDelta"),
    brandSelector: document.querySelector("#brandSelector"),
    toolMetricsGrid: document.querySelector("#toolMetricsGrid"),
    trendGraph: document.querySelector("#trendGraph"),
    chartLabels: document.querySelector("#chartLabels"),
    trendLegend: document.querySelector("#trendLegend"),
    topKeywordsList: document.querySelector("#topKeywordsList"),
    topKeywordsBrandLabel: document.querySelector("#topKeywordsBrandLabel"),
  };
}

export async function initDashboard() {
  const container = view();
  renderLoading(container, "대시보드를 불러오는 중…");

  let trends;
  try {
    trends = await api.getTrends({ weeks: 8 });
  } catch (error) {
    renderError(container, error, { onRetry: initDashboard });
    return;
  }

  const hasAnyData = trends.series.some((s) => s.points.some((p) => toNumber(p.sov) !== null));
  if (!hasAnyData) {
    renderEmpty(container, {
      title: "아직 측정 데이터가 없습니다",
      message: "주간 배치를 한 번도 실행하지 않았습니다. 상단의 '주간 실행' 버튼으로 배치를 실행하면 대시보드가 채워집니다.",
      actionLabel: "지금 주간 실행",
      onAction: async () => {
        const btn = document.querySelector("#runBtn");
        btn?.click();
      },
    });
    return;
  }

  ensureSkeleton();
  const e = els();
  [e.statSov, e.statRank, e.statPrompts, e.statNegative].forEach((el) => {
    if (el) el.textContent = "…";
  });

  let summary, previousSummary, prompts;
  try {
    [summary, prompts] = await Promise.all([api.getDashboardSummary(), api.listPrompts({ is_active: true })]);
    previousSummary = await api.getDashboardSummary(summary.previous_week);
  } catch (error) {
    renderError(container, error, { onRetry: initDashboard });
    return;
  }

  renderBatchStatusBanner(e, summary.week);
  renderStats(e, summary, previousSummary, prompts.length);

  state.trends = trends;
  renderTrendChart(e, trends);

  if (!state.selectedBrandId || !trends.series.some((s) => s.brand_id === state.selectedBrandId)) {
    state.selectedBrandId = trends.series[0]?.brand_id ?? null;
  }
  renderBrandSelector(e, trends.series);
  await Promise.all([loadAndRenderBrandOverview(e), renderTopKeywords(e)]);
}

// 이번 주 배치가 한 번도 안 돌았거나(예: 실행 예정 시각에 PC가 꺼져 있었던 경우), 일부
// 실패했거나, 중간에 멈춘 채로 남아있는지 확인해 배너로 안내한다. 관리자 키가 없으면(401)
// 배너 없이 조용히 넘어간다 — 이 화면은 관리자가 아니어도 볼 수 있어야 하므로.
async function renderBatchStatusBanner(e, weekLabel) {
  if (!e.batchStatusBanner) return;

  let status;
  try {
    status = await api.getBatchStatus(weekLabel);
  } catch (error) {
    if (error instanceof ApiError && error.status === 404) {
      renderBanner(e.batchStatusBanner, {
        text: `이번 주(${weekLabel}) 배치가 아직 실행되지 않았습니다.`,
        actionLabel: "지금 실행",
        onAction: () => document.querySelector("#runBtn")?.click(),
      });
      return;
    }
    e.batchStatusBanner.innerHTML = "";
    return;
  }

  if (status.failed > 0) {
    renderBanner(e.batchStatusBanner, {
      text: `이번 주(${weekLabel}) 실행 중 ${status.failed}건이 실패했습니다(네트워크 오류, CLI 인증 만료 등).`,
      actionLabel: "실패한 것만 재시도",
      onAction: () => runResume(weekLabel),
    });
  } else if (status.pending > 0 || status.running > 0) {
    renderBanner(e.batchStatusBanner, {
      text: `이번 주(${weekLabel}) 배치가 중단되었거나 아직 끝나지 않은 것 같습니다(대기 ${status.pending}건, 진행 중 ${status.running}건) — 실행 중 PC가 꺼졌을 가능성이 있습니다.`,
      actionLabel: "이어서 실행",
      onAction: () => runResume(weekLabel),
    });
  } else {
    e.batchStatusBanner.innerHTML = "";
  }
}

function renderBanner(container, { text, actionLabel, onAction }) {
  container.innerHTML = `
    <div class="batch-status-banner">
      <span>${escapeHtml(text)}</span>
      <button type="button" class="btn small" id="batchStatusBannerAction">${escapeHtml(actionLabel)}</button>
    </div>
  `;
  container.querySelector("#batchStatusBannerAction")?.addEventListener("click", async (event) => {
    const btn = event.currentTarget;
    btn.disabled = true;
    btn.textContent = "처리 중…";
    await onAction();
  });
}

async function runResume(weekLabel) {
  try {
    // resumeBatch()도 트리거와 마찬가지로 즉시 반환한다(FAILED → PENDING 전환만) — 실제 재실행은
    // worker 데몬이 처리하므로 완료 여부는 폴링으로 확인한다(migration_flask_postgres.md §2.5).
    const triggered = await api.resumeBatch(weekLabel);
    showToast(`재실행을 시작했습니다 (대기 ${triggered.pending}건).`);
    const status = await api.pollBatchUntilDone(weekLabel);
    clearWeekDataCache();
    showToast(`재실행 완료 — 성공 ${status.success}건 / 실패 ${status.failed}건`);
    initDashboard();
  } catch (error) {
    showToast(`재실행 실패: ${error.message}`);
  }
}

function renderStats(e, summary, previousSummary, activePromptCount) {
  e.statSov.textContent = formatPercent(summary.total_sov);
  applyDelta(e.statSovDelta, toNumber(summary.sov_delta), { suffix: "%p", positiveIsGood: true });

  e.statRank.textContent = `${summary.rank}위 / ${summary.total_ranked_entities}개`;
  const rankDelta =
    previousSummary && toNumber(summary.sov_delta) !== null ? previousSummary.rank - summary.rank : null;
  applyDelta(e.statRankDelta, rankDelta, { positiveIsGood: true });

  e.statPrompts.textContent = String(activePromptCount);

  e.statNegative.textContent = String(summary.negative_mention_count);
  const negativeDelta =
    toNumber(summary.sov_delta) !== null
      ? summary.negative_mention_count - previousSummary.negative_mention_count
      : null;
  applyDelta(e.statNegativeDelta, negativeDelta, { positiveIsGood: false });
}

function renderBrandSelector(e, series) {
  e.brandSelector.innerHTML = series
    .map(
      (brand) => `
      <button type="button" class="${brand.brand_id === state.selectedBrandId ? "active" : ""}" data-brand-id="${brand.brand_id}">${escapeHtml(brand.brand_name)}</button>
    `
    )
    .join("");
  e.brandSelector.querySelectorAll("button").forEach((btn) => {
    btn.addEventListener("click", async () => {
      state.selectedBrandId = Number(btn.dataset.brandId);
      const e2 = els();
      renderBrandSelector(e2, state.trends.series);
      await Promise.all([loadAndRenderBrandOverview(e2), renderTopKeywords(e2)]);
    });
  });
}

async function loadAndRenderBrandOverview(e) {
  if (!state.selectedBrandId) {
    e.toolMetricsGrid.innerHTML = "";
    return;
  }
  e.toolMetricsGrid.innerHTML = `<div class="state-box"><div class="spinner" aria-hidden="true"></div></div>`;
  try {
    const overview = await api.getBrandOverview(state.selectedBrandId);
    if (!overview.providers.length) {
      renderEmpty(e.toolMetricsGrid, { title: "이 브랜드의 채널별 데이터가 없습니다", message: "" });
      return;
    }
    e.toolMetricsGrid.innerHTML = overview.providers
      .map(
        (p) => `
        <article class="tool-metric-card">
          <header>
            <h4>${escapeHtml(providerDisplayName(p.llm_provider_name))}</h4>
            <span class="tool-score">${formatPercent(p.sov)}</span>
          </header>
          <div class="metric-row">
            <span>AI SOV</span>
            <strong>${formatPercent(p.sov)}</strong>
          </div>
          <div class="metric-row">
            <span>Mentions</span>
            <strong>${p.mention_count}</strong>
          </div>
          <div class="metric-row">
            <span>Cited pages</span>
            <div class="cited-list">
              ${
                p.cited_pages.length
                  ? p.cited_pages.map((page) => `<span title="${escapeHtml(page)}">${escapeHtml(page)}</span>`).join("")
                  : '<span style="color:var(--muted)">인용 없음</span>'
              }
            </div>
          </div>
        </article>
      `
      )
      .join("");
  } catch (error) {
    renderError(e.toolMetricsGrid, error, { onRetry: () => loadAndRenderBrandOverview(e) });
  }
}

async function renderTopKeywords(e) {
  const brand = state.trends?.series.find((s) => s.brand_id === state.selectedBrandId);
  e.topKeywordsBrandLabel.textContent = brand ? brand.brand_name : "Selected brand";
  e.topKeywordsList.innerHTML = `<div class="state-box"><div class="spinner" aria-hidden="true"></div></div>`;

  let data;
  try {
    data = await loadWeekMentions();
  } catch (error) {
    renderError(e.topKeywordsList, error, { onRetry: () => renderTopKeywords(e) });
    return;
  }

  const byPrompt = new Map();
  for (const row of data.rows) {
    if (row.brandId !== state.selectedBrandId) continue;
    const existing = byPrompt.get(row.promptId);
    if (!existing || row.mentionOrder < existing.mentionOrder) {
      byPrompt.set(row.promptId, row);
    }
  }
  const top = [...byPrompt.values()].sort((a, b) => a.mentionOrder - b.mentionOrder).slice(0, 6);

  if (!top.length) {
    renderEmpty(e.topKeywordsList, {
      title: "언급된 프롬프트가 없습니다",
      message: "이번 주 이 브랜드가 언급된 프롬프트가 아직 없습니다.",
    });
    return;
  }

  e.topKeywordsList.innerHTML = top
    .map(
      (row) => `
      <article class="top-keyword-item">
        <header>
          <strong>${escapeHtml(row.promptText)}</strong>
          <span class="keyword-rank">#${row.mentionOrder}</span>
        </header>
        <div class="keyword-meta">
          <span>${escapeHtml(providerDisplayName(row.providerName))} · ${escapeHtml(row.intent)}</span>
          <span>언급 순서 근사치</span>
        </div>
      </article>
    `
    )
    .join("");
}
