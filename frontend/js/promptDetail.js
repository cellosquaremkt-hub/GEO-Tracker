// 프롬프트 상세 뷰 — GET /prompts/{id}/detail. 채널별 실제 응답 전문 + 브랜드 언급 하이라이트 +
// 감정 + 인용 URL. 응답이 길 수 있어 접기/펼치기를 제공한다(작업 지시 11번).
import * as api from "./api.js";
import { renderError, renderLoading } from "./ui.js";
import { escapeHtml, executionStatusLabel, sentimentLabel } from "./format.js";
import { providerDisplayName } from "./providers.js";

function els() {
  return {
    text: document.querySelector("#promptDetailText"),
    meta: document.querySelector("#promptDetailMeta"),
    executions: document.querySelector("#promptDetailExecutions"),
  };
}

export async function openPromptDetail(promptId) {
  const e = els();
  e.text.textContent = "불러오는 중…";
  e.meta.textContent = "";
  renderLoading(e.executions, "채널별 응답을 불러오는 중…");

  try {
    const detail = await api.getPromptDetail(promptId);
    e.text.textContent = detail.prompt_text;
    e.meta.textContent = `${detail.week} 기준 · 실행 ${detail.executions.length}건`;
    renderExecutions(e.executions, detail.executions);
  } catch (error) {
    e.text.textContent = "프롬프트를 불러오지 못했습니다";
    renderError(e.executions, error, { onRetry: () => openPromptDetail(promptId) });
  }
}

function renderExecutions(container, executions) {
  if (!executions.length) {
    container.innerHTML = `<div class="state-box"><strong>실행 이력이 없습니다</strong><p>이번 주 아직 이 프롬프트가 실행되지 않았습니다.</p></div>`;
    return;
  }

  container.innerHTML = executions
    .map((exec, index) => {
      const bodyId = `exec-body-${index}`;
      if (exec.status !== "success") {
        return `
          <article class="execution-card">
            <header>
              <strong>${escapeHtml(providerDisplayName(exec.llm_provider_name))} · #${exec.repeat_index + 1}</strong>
              <span class="badge ${exec.status === "failed" ? "bad" : "warn"}">${executionStatusLabel(exec.status)}</span>
            </header>
            <div class="response-body">
              <p style="margin:0;color:var(--muted);font-size:13px;">
                ${exec.status === "failed" ? "이 실행은 실패해서 응답이 없습니다." : "아직 실행 중이거나 대기 중입니다."}
              </p>
            </div>
          </article>
        `;
      }

      const highlightedHtml = buildHighlightedHtml(exec.raw_response || "", exec.highlights);
      const mentionsHtml = exec.mentions.length
        ? exec.mentions
            .map(
              (m) => `
          <span class="mention-row">
            <span class="badge ${sentimentBadgeClass(m.sentiment)}">${sentimentLabel(m.sentiment)}</span>
            <strong>${escapeHtml(m.brand_name)}</strong>
            ${m.sentiment_evidence ? `<span style="color:var(--muted)">— ${escapeHtml(m.sentiment_evidence)}</span>` : ""}
          </span>
        `
            )
            .join("")
        : `<span style="color:var(--muted);font-size:12px;">브랜드 언급 없음</span>`;

      const citationsHtml = exec.citations.length
        ? exec.citations
            .map(
              (c) => `
          <span class="citation-row">
            <a href="${escapeHtml(c.url)}" target="_blank" rel="noopener noreferrer">${escapeHtml(c.url)}</a>
            ${c.matched_brand_name ? `<span class="badge good">${escapeHtml(c.matched_brand_name)}</span>` : `<span style="color:var(--muted)">미매칭 도메인</span>`}
          </span>
        `
            )
            .join("")
        : `<span style="color:var(--muted);font-size:12px;">인용 URL 없음(본문 링크 추출 기준)</span>`;

      return `
        <article class="execution-card">
          <header>
            <strong>${escapeHtml(providerDisplayName(exec.llm_provider_name))} · #${exec.repeat_index + 1}</strong>
            <span class="badge good">${executionStatusLabel(exec.status)}</span>
          </header>
          <div class="response-body">
            <div class="response-text" id="${bodyId}">${highlightedHtml}</div>
            <button class="expand-btn" type="button" data-target="${bodyId}">펼치기</button>
            <div>
              <span style="font-size:11px;font-weight:800;color:var(--muted);">브랜드 언급</span>
              <div class="mention-list" style="margin-top:6px;">${mentionsHtml}</div>
            </div>
            <div>
              <span style="font-size:11px;font-weight:800;color:var(--muted);">인용 URL</span>
              <div class="citation-list" style="margin-top:6px;">${citationsHtml}</div>
            </div>
          </div>
        </article>
      `;
    })
    .join("");

  container.querySelectorAll(".expand-btn").forEach((btn) => {
    btn.addEventListener("click", () => {
      const body = container.querySelector(`#${btn.dataset.target}`);
      const expanded = body.classList.toggle("expanded");
      btn.textContent = expanded ? "접기" : "펼치기";
    });
  });
}

function sentimentBadgeClass(sentiment) {
  return { positive: "good", neutral: "neutral", negative: "bad" }[sentiment] || "neutral";
}

// raw_response 문자열 + highlights([{start,end,brand_name}]) 오프셋으로 <mark> 하이라이트를 만든다.
// 텍스트는 LLM이 생성한 임의 문자열(실측 모드에서는 실제 CLI 응답)이므로, 하이라이트 바깥 구간은
// 반드시 escapeHtml을 거쳐야 한다 — 응답 안에 "<script>" 같은 문자열이 그대로 들어있어도 innerHTML
// 삽입 시 실행되지 않게 하기 위해서다.
function buildHighlightedHtml(text, highlights) {
  if (!text) return "";
  const sorted = [...highlights].sort((a, b) => a.start - b.start);
  let cursor = 0;
  let html = "";
  for (const h of sorted) {
    if (h.start < cursor || h.start >= h.end || h.end > text.length) continue; // 겹치거나 범위 밖이면 방어적으로 건너뜀
    html += escapeHtml(text.slice(cursor, h.start));
    html += `<mark title="${escapeHtml(h.brand_name)}">${escapeHtml(text.slice(h.start, h.end))}</mark>`;
    cursor = h.end;
  }
  html += escapeHtml(text.slice(cursor));
  return html;
}
