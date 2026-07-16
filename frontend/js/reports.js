// 리포트 뷰 — 주간 리포트(GET /reports/weekly) + 감정 분석(프롬프트 상세 집계).
import * as api from "./api.js";
import { renderEmpty, renderError, renderLoading } from "./ui.js";
import { escapeHtml, formatDecimal, formatPercent } from "./format.js";
import { loadWeekMentions } from "./weekData.js";

let wired = false;

function els() {
  return {
    tabs: document.querySelector("#reportsTabs"),
    weeklyTab: document.querySelector("#reportsWeeklyTab"),
    sentimentTab: document.querySelector("#reportsSentimentTab"),
    summaryCards: document.querySelector("#reportSummaryCards"),
    vulnerable: document.querySelector("#vulnerablePrompts"),
    competitor: document.querySelector("#competitorAdvantage"),
    sentimentBreakdown: document.querySelector("#sentimentBreakdown"),
  };
}

export async function initReports() {
  const e = els();
  if (!wired) {
    e.tabs.querySelectorAll("button[data-tab]").forEach((btn) => {
      btn.addEventListener("click", () => switchTab(btn.dataset.tab));
    });
    wired = true;
  }
  await loadWeeklyReport();
}

function switchTab(tab) {
  const e = els();
  e.tabs.querySelectorAll("button[data-tab]").forEach((btn) => btn.classList.toggle("active", btn.dataset.tab === tab));
  e.weeklyTab.hidden = tab !== "weekly";
  e.sentimentTab.hidden = tab !== "sentiment";
  if (tab === "sentiment") loadSentiment();
}

async function loadWeeklyReport() {
  const e = els();
  renderLoading(e.summaryCards, "주간 리포트를 불러오는 중…");
  e.vulnerable.innerHTML = "";
  e.competitor.innerHTML = "";
  try {
    const report = await api.getWeeklyReport();
    renderSummaryCards(e.summaryCards, report.summary);
    renderVulnerable(e.vulnerable, report.vulnerable_prompts);
    renderCompetitorAdvantage(e.competitor, report.competitor_advantage_prompts);
  } catch (error) {
    renderError(e.summaryCards, error, { onRetry: loadWeeklyReport });
  }
}

function renderSummaryCards(container, summary) {
  container.innerHTML = `
    <article class="stat-card">
      <div class="label"><span>실행 건수</span></div>
      <div class="value">${summary.total_execution_runs}</div>
    </article>
    <article class="stat-card">
      <div class="label"><span>성공</span></div>
      <div class="value" style="color:var(--good)">${summary.success_count}</div>
    </article>
    <article class="stat-card">
      <div class="label"><span>실패</span></div>
      <div class="value" style="color:${summary.failed_count > 0 ? "var(--bad)" : "var(--ink)"}">${summary.failed_count}</div>
    </article>
    <article class="stat-card">
      <div class="label"><span>자사 합산 SOV</span></div>
      <div class="value">${formatPercent(summary.own_total_sov)}</div>
    </article>
  `;
}

function renderVulnerable(container, prompts) {
  if (!prompts.length) {
    renderEmpty(container, { title: "취약 프롬프트가 없습니다", message: "이번 주 미노출/부정 언급으로 분류된 프롬프트가 없습니다." });
    return;
  }
  container.innerHTML = prompts
    .map(
      (p) => `
      <div class="issue">
        <div class="issue-head">
          <strong>${escapeHtml(p.prompt_text)}</strong>
          <span class="priority" style="background:${p.priority === "High" ? "#fde9e7" : "#fff3d7"};color:${p.priority === "High" ? "var(--bad)" : "#9a6206"}">${escapeHtml(p.priority)}</span>
        </div>
        <p>${escapeHtml(p.intent)} · ${escapeHtml(p.reason)}</p>
      </div>
    `
    )
    .join("");
}

function renderCompetitorAdvantage(container, prompts) {
  if (!prompts.length) {
    renderEmpty(container, { title: "경쟁사 우위 프롬프트가 없습니다", message: "경쟁사가 우리보다 평균 순위가 앞선 프롬프트가 없습니다." });
    return;
  }
  container.innerHTML = prompts
    .map(
      (p) => `
      <div class="issue">
        <div class="issue-head">
          <strong>${escapeHtml(p.prompt_text)}</strong>
        </div>
        <p>
          우리 평균 순위 ${p.own_avg_rank !== null ? formatDecimal(p.own_avg_rank) : "언급 없음"} ·
          ${escapeHtml(p.leading_competitor_name)} 평균 순위 ${formatDecimal(p.leading_competitor_avg_rank)}
        </p>
      </div>
    `
    )
    .join("");
}

async function loadSentiment() {
  const e = els();
  renderLoading(e.sentimentBreakdown, "감정 데이터를 집계하는 중…");
  try {
    const { rows } = await loadWeekMentions();
    if (!rows.length) {
      renderEmpty(e.sentimentBreakdown, {
        title: "집계할 언급이 없습니다",
        message: "이번 주 브랜드 언급이 아직 없습니다.",
      });
      return;
    }
    const byBrand = new Map();
    for (const row of rows) {
      if (!byBrand.has(row.brandId)) {
        byBrand.set(row.brandId, { name: row.brandName, positive: 0, neutral: 0, negative: 0 });
      }
      byBrand.get(row.brandId)[row.sentiment] += 1;
    }
    e.sentimentBreakdown.innerHTML = [...byBrand.values()]
      .map((brand) => {
        const total = brand.positive + brand.neutral + brand.negative;
        const pct = (n) => (total ? (n / total) * 100 : 0);
        return `
          <div>
            <div class="brand-meta" style="margin-bottom:6px;">
              <strong style="color:var(--ink);">${escapeHtml(brand.name)}</strong>
              <span>긍정 ${brand.positive} · 중립 ${brand.neutral} · 부정 ${brand.negative}</span>
            </div>
            <div class="sentiment-bar">
              <span class="positive" style="width:${pct(brand.positive)}%"></span>
              <span class="neutral" style="width:${pct(brand.neutral)}%"></span>
              <span class="negative" style="width:${pct(brand.negative)}%"></span>
            </div>
          </div>
        `;
      })
      .join("");
  } catch (error) {
    renderError(e.sentimentBreakdown, error, { onRetry: loadSentiment });
  }
}
