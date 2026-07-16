// GEO Weekly Tracker — 백엔드 REST API fetch 래퍼.
//
// 빌드 도구가 없는 정적 파일 프로젝트라 .env 값을 JS로 주입할 방법이 없다 — API_BASE는
// "프론트가 열린 호스트명 + 8000번 포트"로 유도한다. 이렇게 하면 http://localhost:5500 로 열든
// http://127.0.0.1:5500 으로 열든 같은 호스트명의 API로 맞춰 붙는다(백엔드 CORS_ORIGINS도 두
// 표기를 모두 허용하도록 .env에 등록해뒀다 — CLAUDE.md 참조).
export const API_BASE = `${location.protocol}//${location.hostname}:8000`;

const ADMIN_KEY_STORAGE = "geo-tracker-admin-key";

export function getAdminKey() {
  return localStorage.getItem(ADMIN_KEY_STORAGE) || "";
}

export function setAdminKey(key) {
  localStorage.setItem(ADMIN_KEY_STORAGE, key);
}

export class ApiError extends Error {
  constructor(message, { status, detail } = {}) {
    super(message);
    this.name = "ApiError";
    this.status = status;
    this.detail = detail;
  }
}

// fetch()가 네트워크 단계에서 실패(TypeError)했을 때 — 백엔드 프로세스가 아예 안 떠 있거나
// CORS/네트워크 문제로 요청 자체가 도달하지 못한 경우. ApiError(서버가 응답은 했지만 4xx/5xx)와
// 구분해야 "백엔드 미기동" 안내를 따로 보여줄 수 있다.
export class ApiConnectionError extends Error {
  constructor(message) {
    super(message);
    this.name = "ApiConnectionError";
  }
}

function buildUrl(path, params) {
  const url = new URL(API_BASE + path);
  if (params) {
    for (const [key, value] of Object.entries(params)) {
      if (value === undefined || value === null || value === "") continue;
      url.searchParams.set(key, value);
    }
  }
  return url;
}

async function request(path, { method = "GET", params, body, admin = false, raw = false } = {}) {
  const url = buildUrl(path, params);
  const headers = {};
  if (body !== undefined) headers["Content-Type"] = "application/json";
  if (admin) headers["X-Admin-Api-Key"] = getAdminKey();

  let response;
  try {
    response = await fetch(url, {
      method,
      headers,
      body: body !== undefined ? JSON.stringify(body) : undefined,
    });
  } catch {
    // TypeError: Failed to fetch — 백엔드 미기동/네트워크 단절. 응답 자체를 못 받았다.
    throw new ApiConnectionError(`${API_BASE}에 연결할 수 없습니다.`);
  }

  if (!response.ok) {
    let detail = response.statusText;
    try {
      const payload = await response.json();
      detail = payload.detail || detail;
    } catch {
      // JSON이 아닌 에러 본문(드묾) — statusText로 대체.
    }
    throw new ApiError(`${method} ${path} 실패: ${detail}`, { status: response.status, detail });
  }

  if (raw) return response;
  if (response.status === 204) return null;
  return response.json();
}

// --- 공개 조회 엔드포인트 (인증 불필요) ---------------------------------------------------

export function getHealth() {
  return request("/health");
}

export function getDashboardSummary(week) {
  return request("/dashboard/summary", { params: { week } });
}

export function getBrandOverview(brandId, week) {
  return request(`/brands/${brandId}/overview`, { params: { week } });
}

export function getTrends({ weeks = 8, week } = {}) {
  return request("/trends", { params: { weeks, week } });
}

export function listPrompts(filters = {}) {
  return request("/prompts", { params: filters });
}

export function getPromptDetail(promptId, week) {
  return request(`/prompts/${promptId}/detail`, { params: { week } });
}

export async function getExportCsvBlob(week) {
  const response = await request("/export/csv", { params: { week }, raw: true });
  return response.blob();
}

export function getWeeklyReport(week) {
  return request("/reports/weekly", { params: { week } });
}

// --- 관리자 엔드포인트 (X-Admin-Api-Key 필요) ---------------------------------------------

export function listBrandsAdmin() {
  return request("/brands", { admin: true });
}

export function getBrandAdmin(brandId) {
  return request(`/brands/${brandId}`, { admin: true });
}

export function createBrand({ name, isOwn = false, aliases = [], domains = [] }) {
  return request("/brands", {
    method: "POST",
    admin: true,
    body: { name, is_own: isOwn, aliases, domains },
  });
}

export function updateBrand(brandId, { name, isOwn, aliases, domains } = {}) {
  const body = {};
  if (name !== undefined) body.name = name;
  if (isOwn !== undefined) body.is_own = isOwn;
  if (aliases !== undefined) body.aliases = aliases;
  if (domains !== undefined) body.domains = domains;
  return request(`/brands/${brandId}`, { method: "PUT", admin: true, body });
}

export function createPrompt({ text, intent, target, priority, language, supersedesId = null }) {
  return request("/prompts", {
    method: "POST",
    admin: true,
    body: { text, intent, target, priority, language, supersedes_id: supersedesId },
  });
}

export function deactivatePrompt(promptId) {
  return request(`/prompts/${promptId}/deactivate`, { method: "PUT", admin: true });
}

export function listLlmProvidersAdmin() {
  return request("/llm-providers", { admin: true });
}

export function updateLlmProvider(providerId, { isActive } = {}) {
  const body = {};
  if (isActive !== undefined) body.is_active = isActive;
  return request(`/llm-providers/${providerId}`, { method: "PUT", admin: true, body });
}

// trigger/resume는 즉시 응답한다 — execution_run을 PENDING(또는 FAILED→PENDING)으로 만들기만
// 하고 실제 CLI 실행은 별도 worker 데몬이 백그라운드에서 처리한다. 반환된 status는 "방금 만든
// PENDING 잡 수"일 뿐 최종 결과가 아니므로, 완료를 확인하려면 pollBatchUntilDone()으로
// GET /runs/{batch_id}/status를 폴링해야 한다.
export function triggerBatch() {
  return request("/runs/trigger", { method: "POST", admin: true });
}

export function resumeBatch(batchId) {
  return request(`/runs/${batchId}/resume`, { method: "POST", admin: true });
}

export function getBatchStatus(batchId) {
  return request(`/runs/${batchId}/status`, { admin: true });
}

// pending+running이 0이 될 때까지 GET /runs/{batch_id}/status를 일정 간격으로 폴링한다.
// onTick이 주어지면 매 폴링마다 중간 상태를 콜백으로 알려준다(진행 표시용).
export async function pollBatchUntilDone(batchId, { intervalMs = 2500, onTick } = {}) {
  for (;;) {
    const status = await getBatchStatus(batchId);
    if (onTick) onTick(status);
    if (status.pending === 0 && status.running === 0) return status;
    await new Promise((resolve) => setTimeout(resolve, intervalMs));
  }
}

export function getBatchConfig() {
  return request("/batch-config", { admin: true });
}

export function updateBatchConfig(repeatCount) {
  return request("/batch-config", {
    method: "PUT",
    admin: true,
    body: { repeat_count: repeatCount },
  });
}
