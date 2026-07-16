// 로딩/에러/빈 상태 공통 렌더러 + 토스트. 모든 뷰 모듈이 데이터를 그리기 전/실패 시 이 함수들로
// container를 채운다 — 화면마다 로딩/에러 마크업을 새로 짜지 않기 위함(작업 지시 13, 14번).
import { ApiConnectionError, ApiError } from "./api.js";

export function renderLoading(container, message = "불러오는 중…") {
  container.innerHTML = `
    <div class="state-box">
      <div class="spinner" aria-hidden="true"></div>
      <p>${message}</p>
    </div>
  `;
}

export function renderEmpty(container, { title = "데이터가 없습니다", message = "", actionLabel, onAction } = {}) {
  container.innerHTML = `
    <div class="state-box">
      <strong>${title}</strong>
      ${message ? `<p>${message}</p>` : ""}
      ${actionLabel ? `<button class="btn primary" type="button" id="__emptyStateAction">${actionLabel}</button>` : ""}
    </div>
  `;
  if (actionLabel && onAction) {
    container.querySelector("#__emptyStateAction")?.addEventListener("click", onAction);
  }
}

export function renderError(container, error, { onRetry } = {}) {
  const message = error instanceof Error ? error.message : String(error);
  container.innerHTML = `
    <div class="state-box error">
      <strong>문제가 발생했습니다</strong>
      <p>${message}</p>
      ${onRetry ? '<button class="btn" type="button" id="__errorRetry">다시 시도</button>' : ""}
    </div>
  `;
  if (onRetry) container.querySelector("#__errorRetry")?.addEventListener("click", onRetry);
}

// 뷰 렌더 함수를 감싸서 로딩→성공/실패를 자동 처리한다.
// loader: async () => data,  render: (data) => void
export async function withLoadingState(container, loader, render, options = {}) {
  renderLoading(container, options.loadingMessage);
  try {
    const data = await loader();
    render(data);
  } catch (error) {
    if (error instanceof ApiConnectionError) {
      // 개별 뷰에서 굳이 다시 안내하지 않는다 — main.js의 전역 연결 실패 화면이 이미 떴을
      // 것이므로, 여기서는 조용히 재시도 버튼만 보여준다.
      renderError(container, new Error("백엔드에 연결할 수 없습니다."), {
        onRetry: () => withLoadingState(container, loader, render, options),
      });
      return;
    }
    if (error instanceof ApiError && error.status === 404) {
      renderEmpty(container, {
        title: options.notFoundTitle || "데이터를 찾을 수 없습니다",
        message: error.detail || "",
      });
      return;
    }
    renderError(container, error, {
      onRetry: () => withLoadingState(container, loader, render, options),
    });
  }
}

let toastTimer = null;
export function showToast(message) {
  const el = document.querySelector("#toast");
  if (!el) return;
  el.textContent = message;
  el.classList.add("show");
  window.clearTimeout(toastTimer);
  toastTimer = window.setTimeout(() => el.classList.remove("show"), 2400);
}
