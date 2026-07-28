// 키워드(프롬프트) 목록 뷰 — GET /prompts (필터) + 행 클릭 시 상세로 이동.
import * as api from "./api.js";
import { renderEmpty, renderError, renderLoading } from "./ui.js";
import { escapeHtml } from "./format.js";
import { navigateTo } from "./router.js";
import { openPromptDetail } from "./promptDetail.js";

const TARGET_LABEL = {
  "c-level": "C-Level",
  manager: "Manager",
  practitioner: "Practitioner",
  junior: "Junior",
  seller: "Seller",
  common: "공통",
};

const BRAND_TYPE_LABEL = {
  non_brand_longtail: "비브랜드 롱테일",
  category_representative: "카테고리 대표성",
  competitive_comparison: "경쟁 비교형",
  own_brand: "자사 브랜드",
};

function els() {
  return {
    wrap: document.querySelector("#promptTableWrap"),
    filterTarget: document.querySelector("#filterTarget"),
    filterPriority: document.querySelector("#filterPriority"),
    filterLanguage: document.querySelector("#filterLanguage"),
    filterActive: document.querySelector("#filterActive"),
  };
}

let wired = false;

export async function initKeywords() {
  const e = els();
  if (!wired) {
    [e.filterTarget, e.filterPriority, e.filterLanguage, e.filterActive].forEach((sel) => {
      sel.addEventListener("change", loadPrompts);
    });
    wired = true;
  }
  await loadPrompts();
}

async function loadPrompts() {
  const e = els();
  renderLoading(e.wrap, "프롬프트를 불러오는 중…");
  const filters = {
    target: e.filterTarget.value || undefined,
    priority: e.filterPriority.value || undefined,
    language: e.filterLanguage.value || undefined,
    is_active: e.filterActive.value || undefined,
  };
  try {
    const prompts = await api.listPrompts(filters);
    if (!prompts.length) {
      renderEmpty(e.wrap, {
        title: "조건에 맞는 프롬프트가 없습니다",
        message: "필터를 조정하거나 Settings에서 새 키워드를 추가하세요.",
      });
      return;
    }
    renderTable(e.wrap, prompts);
  } catch (error) {
    renderError(e.wrap, error, { onRetry: loadPrompts });
  }
}

function renderTable(wrap, prompts) {
  wrap.innerHTML = `
    <table>
      <thead>
        <tr>
          <th>프롬프트</th>
          <th>타겟</th>
          <th>우선순위</th>
          <th>언어</th>
          <th>상태</th>
          <th>버전</th>
          <th>관리</th>
        </tr>
      </thead>
      <tbody>
        ${prompts
          .map(
            (p) => `
          <tr class="clickable-row" data-prompt-id="${p.id}">
            <td>
              <div class="keyword-cell">
                <strong>${escapeHtml(p.text)}</strong>
                <span>
                  ${escapeHtml(p.intent)}
                  ${p.brand_type ? ` · ${escapeHtml(BRAND_TYPE_LABEL[p.brand_type] || p.brand_type)}` : ""}
                  ${p.source === "excel_import" ? `<span class="badge neutral" title="${escapeHtml(p.source_file || "")}">엑셀 가져옴</span>` : ""}
                </span>
              </div>
            </td>
            <td>${TARGET_LABEL[p.target] || escapeHtml(p.target)}</td>
            <td><span class="priority" style="background:${priorityBg(p.priority)};color:${priorityColor(p.priority)}">${escapeHtml(p.priority)}</span></td>
            <td>${p.language === "ko" ? "한국어" : "English"}</td>
            <td><span class="badge ${p.is_active ? "good" : "neutral"}">${p.is_active ? "활성" : "비활성"}</span></td>
            <td>v${p.version}</td>
            <td>
              ${
                p.is_active
                  ? `<button type="button" class="btn ghost small" data-deactivate-id="${p.id}">비활성화</button>`
                  : `<span class="muted">—</span>`
              }
            </td>
          </tr>
        `
          )
          .join("")}
      </tbody>
    </table>
  `;
  wrap.querySelectorAll("tr[data-prompt-id]").forEach((row) => {
    row.addEventListener("click", (event) => {
      if (event.target.closest("[data-deactivate-id]")) return;
      navigateTo("prompt-detail");
      openPromptDetail(Number(row.dataset.promptId));
    });
  });
  wrap.querySelectorAll("[data-deactivate-id]").forEach((button) => {
    button.addEventListener("click", async (event) => {
      event.stopPropagation();
      const promptId = Number(button.dataset.deactivateId);
      const promptText = button.closest("tr").querySelector("strong")?.textContent || "";
      if (!confirm(`이 프롬프트를 비활성화할까요?\n\n"${promptText}"\n\n다음 주부터 측정 대상에서 빠집니다(과거 데이터는 유지됩니다).`)) {
        return;
      }
      button.disabled = true;
      button.textContent = "처리 중…";
      try {
        await api.deactivatePrompt(promptId);
        await loadPrompts();
      } catch (error) {
        alert(`비활성화 실패: ${error.message || error}`);
        button.disabled = false;
        button.textContent = "비활성화";
      }
    });
  });
}

function priorityBg(priority) {
  return { High: "#fde9e7", Medium: "#fff3d7", Low: "#eef2f6" }[priority] || "#eef2f6";
}

function priorityColor(priority) {
  return { High: "var(--bad)", Medium: "#9a6206", Low: "#5a6370" }[priority] || "#5a6370";
}
