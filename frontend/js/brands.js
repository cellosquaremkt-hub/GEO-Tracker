// 브랜드 뷰 — 브랜드별 AI Overview(개요 탭) + 인용 출처 도메인 분석(인용 탭).
import * as api from "./api.js";
import { ApiError } from "./api.js";
import { renderEmpty, renderError, renderLoading } from "./ui.js";
import { escapeHtml, formatPercent } from "./format.js";
import { providerDisplayName } from "./providers.js";

let activeTab = "overview";
let wired = false;
let brandListCache = null;

function els() {
  return {
    tabs: document.querySelector("#brandsTabs"),
    overviewTab: document.querySelector("#brandsOverviewTab"),
    citationsTab: document.querySelector("#brandsCitationsTab"),
    grid: document.querySelector("#brandsGrid"),
    citationAnalysis: document.querySelector("#citationAnalysis"),
  };
}

export async function initBrands() {
  const e = els();
  if (!wired) {
    e.tabs.querySelectorAll("button[data-tab]").forEach((btn) => {
      btn.addEventListener("click", () => switchTab(btn.dataset.tab));
    });
    wired = true;
  }
  await loadOverview();
}

function switchTab(tab) {
  activeTab = tab;
  const e = els();
  e.tabs.querySelectorAll("button[data-tab]").forEach((btn) => btn.classList.toggle("active", btn.dataset.tab === tab));
  e.overviewTab.hidden = tab !== "overview";
  e.citationsTab.hidden = tab !== "citations";
  if (tab === "citations") loadCitations();
}

// GET /brands는 ADMIN 전용이라 is_own(자사/경쟁사 구분)까지 보려면 관리자 키가 필요하다.
// 키가 없거나 틀려도 브랜드 화면 자체는 죽지 않게, 실패하면 공개 엔드포인트(/trends)로 만든
// 브랜드 id+name 목록으로 조용히 대체한다(자사/경쟁사 태그만 빠진다).
async function getBrandList() {
  if (brandListCache) return brandListCache;
  try {
    const brands = await api.listBrandsAdmin();
    brandListCache = brands.map((b) => ({ id: b.id, name: b.name, isOwn: b.is_own }));
  } catch (error) {
    if (!(error instanceof ApiError)) throw error;
    const trends = await api.getTrends({ weeks: 1 });
    brandListCache = trends.series.map((s) => ({ id: s.brand_id, name: s.brand_name, isOwn: undefined }));
  }
  return brandListCache;
}

async function loadOverview() {
  const e = els();
  renderLoading(e.grid, "브랜드 목록을 불러오는 중…");
  try {
    const brands = await getBrandList();
    if (!brands.length) {
      renderEmpty(e.grid, { title: "등록된 브랜드가 없습니다" });
      return;
    }
    const overviews = await Promise.all(
      brands.map((b) => api.getBrandOverview(b.id).catch(() => null))
    );
    e.grid.innerHTML = brands
      .map((brand, index) => renderBrandCard(brand, overviews[index]))
      .join("");
  } catch (error) {
    renderError(e.grid, error, { onRetry: loadOverview });
  }
}

function renderBrandCard(brand, overview) {
  const providers = overview?.providers || [];
  return `
    <article class="brand-card">
      <header>
        <h4>${escapeHtml(brand.name)}</h4>
        ${brand.isOwn === true ? '<span class="tag-own">자사</span>' : brand.isOwn === false ? '<span class="badge neutral">경쟁사</span>' : ""}
      </header>
      ${
        providers.length
          ? providers
              .map(
                (p) => `
          <div>
            <div class="brand-meta"><span>${escapeHtml(providerDisplayName(p.llm_provider_name))}</span><span>${formatPercent(p.sov)} · 언급 ${p.mention_count}</span></div>
            <div class="share-line"><span style="width:${Math.min(100, Math.max(0, Number(p.sov) || 0))}%"></span></div>
          </div>
        `
              )
              .join("")
          : `<p style="margin:0;color:var(--muted);font-size:12px;">이번 주 채널별 데이터가 없습니다.</p>`
      }
    </article>
  `;
}

async function loadCitations() {
  const e = els();
  renderLoading(e.citationAnalysis, "인용 출처를 집계하는 중…");
  try {
    const brands = await getBrandList();
    const overviews = await Promise.all(brands.map((b) => api.getBrandOverview(b.id).catch(() => null)));

    const sections = brands
      .map((brand, index) => {
        const overview = overviews[index];
        const domainCounts = new Map();
        for (const provider of overview?.providers || []) {
          for (const page of provider.cited_pages) {
            const domain = extractDomain(page);
            domainCounts.set(domain, (domainCounts.get(domain) || 0) + 1);
          }
        }
        if (!domainCounts.size) return null;
        const total = [...domainCounts.values()].reduce((a, b) => a + b, 0);
        const rows = [...domainCounts.entries()]
          .sort((a, b) => b[1] - a[1])
          .map(
            ([domain, count]) => `
            <div class="domain-bar-row">
              <span class="domain-name" title="${escapeHtml(domain)}">${escapeHtml(domain)}</span>
              <div class="domain-bar-track"><span style="width:${(count / total) * 100}%"></span></div>
              <span>${count}회</span>
            </div>
          `
          )
          .join("");
        return `
          <div>
            <strong style="font-size:13px;">${escapeHtml(brand.name)}</strong>
            <div style="margin-top:6px;">${rows}</div>
          </div>
        `;
      })
      .filter(Boolean);

    if (!sections.length) {
      renderEmpty(e.citationAnalysis, {
        title: "인용 데이터가 없습니다",
        message: "이번 주 응답에서 추출된 인용 URL이 없습니다.",
      });
      return;
    }
    e.citationAnalysis.innerHTML = sections.join('<hr style="border:none;border-top:1px solid var(--line);margin:14px 0;">');
  } catch (error) {
    renderError(e.citationAnalysis, error, { onRetry: loadCitations });
  }
}

function extractDomain(url) {
  try {
    return new URL(url).hostname;
  } catch {
    return url;
  }
}
