// Settings 드로어 — 관리자 키, 키워드(프롬프트) 추가, 브랜드 ID 기반 CRUD, AI 측정 채널 토글.
import * as api from "./api.js";
import { ApiError } from "./api.js";
import { escapeHtml } from "./format.js";
import { providerDisplayName } from "./providers.js";
import { showToast } from "./ui.js";
import { clearWeekDataCache } from "./weekData.js";

let wired = false;

function els() {
  return {
    adminKeyInput: document.querySelector("#adminKeyInput"),
    saveAdminKeyBtn: document.querySelector("#saveAdminKeyBtn"),
    keywordForm: document.querySelector("#keywordForm"),
    keywordInput: document.querySelector("#keywordInput"),
    intentInput: document.querySelector("#intentInput"),
    targetInput: document.querySelector("#targetInput"),
    priorityInput: document.querySelector("#priorityInput"),
    languageInput: document.querySelector("#languageInput"),
    brandManageList: document.querySelector("#brandManageList"),
    brandForm: document.querySelector("#brandForm"),
    newBrandName: document.querySelector("#newBrandName"),
    newBrandIsOwn: document.querySelector("#newBrandIsOwn"),
    toolToggleList: document.querySelector("#toolToggleList"),
    repeatCountInput: document.querySelector("#repeatCountInput"),
    saveRepeatCountBtn: document.querySelector("#saveRepeatCountBtn"),
    promptImportForm: document.querySelector("#promptImportForm"),
    promptImportFile: document.querySelector("#promptImportFile"),
    promptImportResult: document.querySelector("#promptImportResult"),
  };
}

export function initSettingsOnce() {
  if (wired) return;
  wired = true;
  const e = els();

  e.adminKeyInput.value = api.getAdminKey();
  e.saveAdminKeyBtn.addEventListener("click", () => {
    api.setAdminKey(e.adminKeyInput.value.trim());
    showToast("관리자 키를 저장했습니다.");
    loadBrandManageList();
    loadToolToggleList();
    loadRepeatCount();
  });

  e.saveRepeatCountBtn.addEventListener("click", async () => {
    const value = Number(e.repeatCountInput.value);
    if (!Number.isInteger(value) || value < 1 || value > 20) {
      showToast("반복 횟수는 1~20 사이의 정수로 입력하세요.");
      return;
    }
    try {
      await api.updateBatchConfig(value);
      showToast("반복 횟수를 저장했습니다. 다음 실행부터 바로 적용됩니다.");
    } catch (error) {
      showToast(describeError(error, "반복 횟수 저장 실패"));
    }
  });

  e.keywordForm.addEventListener("submit", async (event) => {
    event.preventDefault();
    try {
      await api.createPrompt({
        text: e.keywordInput.value.trim(),
        intent: e.intentInput.value.trim(),
        target: e.targetInput.value,
        priority: e.priorityInput.value,
        language: e.languageInput.value,
      });
      e.keywordForm.reset();
      clearWeekDataCache();
      showToast("키워드(프롬프트)가 추가되었습니다.");
    } catch (error) {
      showToast(describeError(error, "키워드 추가 실패"));
    }
  });

  e.promptImportForm.addEventListener("submit", async (event) => {
    event.preventDefault();
    const file = e.promptImportFile.files[0];
    if (!file) return;
    e.promptImportResult.textContent = "업로드 중…";
    try {
      const result = await api.importPromptsExcel(file);
      e.promptImportForm.reset();
      clearWeekDataCache();
      e.promptImportResult.innerHTML = `<span style="color:var(--good);">완료: ${result.rows_processed}개 행 → ${result.prompts_created}개 프롬프트 생성(${escapeHtml(result.source_file)})</span>`;
      showToast("엑셀 업로드가 완료되었습니다.");
    } catch (error) {
      renderPromptImportError(error);
    }
  });

  e.brandForm.addEventListener("submit", async (event) => {
    event.preventDefault();
    const name = e.newBrandName.value.trim();
    if (!name) return;
    try {
      await api.createBrand({ name, isOwn: e.newBrandIsOwn.value === "true" });
      e.brandForm.reset();
      showToast("브랜드가 추가되었습니다.");
      loadBrandManageList();
    } catch (error) {
      showToast(describeError(error, "브랜드 추가 실패"));
    }
  });
}

export function refreshSettings() {
  initSettingsOnce();
  loadBrandManageList();
  loadToolToggleList();
  loadRepeatCount();
}

// --- 배치 반복 횟수(REPEAT_COUNT) — 관리자가 .env/서버 재시작 없이 직접 조정 ------------------

async function loadRepeatCount() {
  const e = els();
  try {
    const config = await api.getBatchConfig();
    e.repeatCountInput.value = config.repeat_count;
    e.repeatCountInput.disabled = false;
    e.saveRepeatCountBtn.disabled = false;
  } catch (error) {
    e.repeatCountInput.disabled = true;
    e.saveRepeatCountBtn.disabled = true;
    if (!(error instanceof ApiError && error.status === 401)) {
      showToast(describeError(error, "반복 횟수 조회 실패"));
    }
  }
}

function renderPromptImportError(error) {
  const e = els();
  if (error instanceof ApiError && error.status === 401) {
    e.promptImportResult.innerHTML = `<span style="color:var(--bad);">관리자 키가 없거나 올바르지 않습니다.</span>`;
    return;
  }
  const rowErrors = error instanceof ApiError ? error.rowErrors || [] : [];
  if (rowErrors.length) {
    const items = rowErrors
      .slice(0, 20)
      .map((r) => `<li>${r.row_number}행: ${escapeHtml(r.message)}</li>`)
      .join("");
    const more = rowErrors.length > 20 ? `<p>...외 ${rowErrors.length - 20}건 더</p>` : "";
    e.promptImportResult.innerHTML = `<span style="color:var(--bad);">${rowErrors.length}개 행에서 오류가 발견되어 아무 것도 만들지 않았습니다:</span><ul style="margin:6px 0 0 18px;">${items}</ul>${more}`;
    return;
  }
  e.promptImportResult.innerHTML = `<span style="color:var(--bad);">${escapeHtml(describeError(error, "업로드 실패"))}</span>`;
}

function describeError(error, fallback) {
  if (error instanceof ApiError && error.status === 401) return "관리자 키가 없거나 올바르지 않습니다.";
  if (error instanceof ApiError) return error.detail || fallback;
  return fallback;
}

// --- 브랜드 관리: 고유 ID로만 참조한다(작업 지시 7번 — 배열 순서 매핑 금지). ---------------

async function loadBrandManageList() {
  const e = els();
  e.brandManageList.innerHTML = `<div class="state-box"><div class="spinner" aria-hidden="true"></div></div>`;
  try {
    const brands = await api.listBrandsAdmin();
    renderBrandManageList(brands);
  } catch (error) {
    if (error instanceof ApiError && error.status === 401) {
      e.brandManageList.innerHTML = `<div class="state-box"><p>관리자 키를 입력하고 저장하면 브랜드 관리 기능을 쓸 수 있습니다.</p></div>`;
      return;
    }
    e.brandManageList.innerHTML = `<div class="state-box error"><p>브랜드 목록을 불러오지 못했습니다: ${escapeHtml(error.message)}</p></div>`;
  }
}

function renderBrandManageList(brands) {
  const e = els();
  if (!brands.length) {
    e.brandManageList.innerHTML = `<div class="state-box"><p>등록된 브랜드가 없습니다.</p></div>`;
    return;
  }
  e.brandManageList.innerHTML = brands
    .map(
      (b) => `
      <div class="brand-manage-card" data-brand-id="${b.id}">
        <header>
          <strong>${escapeHtml(b.name)}</strong>
          <span class="${b.is_own ? "tag-own" : "badge neutral"}">${b.is_own ? "자사" : "경쟁사"}</span>
        </header>
        <div>
          <span style="font-size:11px;font-weight:800;color:var(--muted);">별칭</span>
          <div class="chips" data-field="aliases">
            ${b.aliases.map((a) => aliasChip(a.alias_text)).join("")}
          </div>
          <div class="chip-input-row">
            <input type="text" placeholder="별칭 추가 후 Enter" data-add="aliases">
          </div>
        </div>
        <div>
          <span style="font-size:11px;font-weight:800;color:var(--muted);">도메인</span>
          <div class="chips" data-field="domains">
            ${b.domains.map((d) => aliasChip(d.domain)).join("")}
          </div>
          <div class="chip-input-row">
            <input type="text" placeholder="도메인 추가 후 Enter (예: example.com)" data-add="domains">
          </div>
        </div>
      </div>
    `
    )
    .join("");

  e.brandManageList.querySelectorAll(".brand-manage-card").forEach((card) => {
    const brandId = Number(card.dataset.brandId);
    const brand = brands.find((b) => b.id === brandId);

    card.querySelectorAll(".chip.removable button").forEach((removeBtn) => {
      removeBtn.addEventListener("click", async () => {
        const field = removeBtn.closest(".chips").dataset.field;
        const valueToRemove = removeBtn.dataset.value;
        const current =
          field === "aliases" ? brand.aliases.map((a) => a.alias_text) : brand.domains.map((d) => d.domain);
        const next = current.filter((v) => v !== valueToRemove);
        await patchBrandField(brandId, field, next);
      });
    });

    card.querySelectorAll("input[data-add]").forEach((input) => {
      input.addEventListener("keydown", async (event) => {
        if (event.key !== "Enter") return;
        event.preventDefault();
        const value = input.value.trim();
        if (!value) return;
        const field = input.dataset.add;
        const current =
          field === "aliases" ? brand.aliases.map((a) => a.alias_text) : brand.domains.map((d) => d.domain);
        if (current.includes(value)) {
          showToast("이미 등록된 값입니다.");
          return;
        }
        await patchBrandField(brandId, field, [...current, value]);
      });
    });
  });
}

function aliasChip(text) {
  return `<span class="chip removable"><strong>${escapeHtml(text)}</strong><button type="button" data-value="${escapeHtml(text)}" title="삭제">×</button></span>`;
}

async function patchBrandField(brandId, field, values) {
  try {
    await api.updateBrand(brandId, { [field]: values });
    loadBrandManageList();
  } catch (error) {
    showToast(describeError(error, "브랜드 수정 실패"));
  }
}

// --- 측정 채널(AI 도구) 제외/재추가 토글 (작업 지시 6, 9번) --------------------------------

async function loadToolToggleList() {
  const e = els();
  e.toolToggleList.innerHTML = `<div class="state-box"><div class="spinner" aria-hidden="true"></div></div>`;
  try {
    const providers = await api.listLlmProvidersAdmin();
    renderToolToggleList(providers);
  } catch (error) {
    if (error instanceof ApiError && error.status === 401) {
      e.toolToggleList.innerHTML = `<p style="color:var(--muted);font-size:12px;">관리자 키를 입력하면 측정 채널을 켜고 끌 수 있습니다.</p>`;
      return;
    }
    e.toolToggleList.innerHTML = `<p style="color:var(--bad);font-size:12px;">불러오지 못했습니다: ${escapeHtml(error.message)}</p>`;
  }
}

function renderToolToggleList(providers) {
  const e = els();
  e.toolToggleList.innerHTML = providers
    .map(
      (p) => `
      <button type="button" class="tool-toggle ${p.is_active ? "on" : "off"}" data-provider-id="${p.id}" data-active="${p.is_active}">
        ${escapeHtml(providerDisplayName(p.name))}
        <span class="tag">${p.is_active ? "측정 중" : "비활성"}</span>
      </button>
    `
    )
    .join("");

  e.toolToggleList.querySelectorAll("button[data-provider-id]").forEach((btn) => {
    btn.addEventListener("click", async () => {
      const providerId = Number(btn.dataset.providerId);
      const currentlyActive = btn.dataset.active === "true";
      const activeCount = providers.filter((p) => p.is_active).length;
      if (currentlyActive && activeCount <= 1) {
        showToast("측정 채널은 최소 1개 이상 활성 상태여야 합니다.");
        return;
      }
      try {
        await api.updateLlmProvider(providerId, { isActive: !currentlyActive });
        showToast(!currentlyActive ? "측정 채널을 다시 포함했습니다." : "측정 채널을 제외했습니다.");
        loadToolToggleList();
      } catch (error) {
        showToast(describeError(error, "측정 채널 변경 실패"));
      }
    });
  });
}
