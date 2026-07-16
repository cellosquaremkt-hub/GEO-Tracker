// 앱 엔트리포인트 — 백엔드 연결 확인(작업 지시 14번) → 내비게이션/토글 배선 → 초기 화면 렌더.
import * as api from "./api.js";
import { ApiConnectionError } from "./api.js";
import { navigateTo, onNavigate } from "./router.js";
import { initDashboard } from "./dashboard.js";
import { initKeywords } from "./keywords.js";
import { initBrands } from "./brands.js";
import { initReports } from "./reports.js";
import { initSettingsOnce, refreshSettings } from "./settings.js";
import { showToast } from "./ui.js";
import { clearWeekDataCache } from "./weekData.js";
import { providerDisplayName } from "./providers.js";

const els = {
  connectionScreen: document.querySelector("#connectionScreen"),
  appViews: document.querySelector("#appViews"),
  apiBaseLabel: document.querySelector("#apiBaseLabel"),
  retryConnectionBtn: document.querySelector("#retryConnectionBtn"),
  closeSettingsBtn: document.querySelector("#closeSettingsBtn"),
  appShell: document.querySelector("#appShell"),
  runBtn: document.querySelector("#runBtn"),
  exportBtn: document.querySelector("#exportBtn"),
  sidebarScheduleInfo: document.querySelector("#sidebarScheduleInfo"),
};

els.apiBaseLabel.textContent = api.API_BASE;

const VIEW_LOADERS = {
  dashboard: initDashboard,
  keywords: initKeywords,
  brands: initBrands,
  reports: initReports,
};

onNavigate((viewId) => {
  const loader = VIEW_LOADERS[viewId];
  if (loader) loader();
});

function wireNav() {
  document.querySelectorAll(".nav button[data-view]").forEach((btn) => {
    btn.addEventListener("click", () => {
      const view = btn.dataset.view;
      if (view === "settings") {
        els.appShell.classList.add("settings-open");
        initSettingsOnce();
        refreshSettings();
        return;
      }
      els.appShell.classList.remove("settings-open");
      navigateTo(view);
    });
  });

  els.closeSettingsBtn.addEventListener("click", () => {
    els.appShell.classList.remove("settings-open");
  });
}

function currentViewId() {
  const active = document.querySelector(".nav button.active");
  return active ? active.dataset.view : "dashboard";
}

function wireTopbar() {
  els.runBtn.addEventListener("click", async () => {
    els.runBtn.disabled = true;
    const originalHtml = els.runBtn.innerHTML;
    els.runBtn.textContent = "실행 중…";
    try {
      // 트리거는 execution_run을 PENDING으로 만들기만 하고 즉시 반환한다 — 실제 CLI 실행은
      // worker 데몬이 백그라운드에서 처리하므로, 완료 여부는 상태 폴링으로 확인해야 한다
      // (migration_flask_postgres.md §2.5).
      const triggered = await api.triggerBatch();
      showToast(`주간 실행을 시작했습니다 (대기 ${triggered.pending}건) — 완료되면 알려드립니다.`);

      const status = await api.pollBatchUntilDone(triggered.batch_id, {
        onTick: (s) => {
          els.runBtn.textContent = `실행 중… (대기 ${s.pending} / 진행 ${s.running})`;
        },
      });
      clearWeekDataCache();
      showToast(`주간 실행 완료 — 성공 ${status.success}건 / 실패 ${status.failed}건`);
      const loader = VIEW_LOADERS[currentViewId()];
      if (loader) loader();
    } catch (error) {
      showToast(`주간 실행 실패: ${error.message}`);
    } finally {
      els.runBtn.disabled = false;
      els.runBtn.innerHTML = originalHtml;
    }
  });

  els.exportBtn.addEventListener("click", async () => {
    try {
      const blob = await api.getExportCsvBlob();
      const url = URL.createObjectURL(blob);
      const a = document.createElement("a");
      a.href = url;
      a.download = "geo-weekly-tracker.csv";
      a.click();
      URL.revokeObjectURL(url);
      showToast("CSV 파일을 내려받았습니다.");
    } catch (error) {
      showToast(`CSV 내보내기 실패: ${error.message}`);
    }
  });
}

async function loadSidebarInfo() {
  let names;
  try {
    const providers = await api.listLlmProvidersAdmin();
    names = providers.filter((p) => p.is_active).map((p) => providerDisplayName(p.name));
  } catch {
    // 관리자 키가 아직 없으면 401 — 현재 기본 활성 채널(3종)로 대체 표시한다.
    names = ["Claude Code CLI", "Codex CLI", "Gemini CLI"];
  }
  els.sidebarScheduleInfo.innerHTML = `WEEKLY_BATCH_CRON 설정에 따름 (기본: 매주 월요일 09:00 KST)<br>${names.join(", ")}`;
}

async function checkBackendReachable() {
  try {
    await api.getHealth();
    return true;
  } catch (error) {
    return !(error instanceof ApiConnectionError);
  }
}

async function boot() {
  const reachable = await checkBackendReachable();
  if (!reachable) {
    els.connectionScreen.hidden = false;
    els.appViews.hidden = true;
    return;
  }
  els.connectionScreen.hidden = true;
  els.appViews.hidden = false;

  wireNav();
  wireTopbar();
  loadSidebarInfo();
  navigateTo("dashboard");
}

els.retryConnectionBtn.addEventListener("click", boot);

boot();
