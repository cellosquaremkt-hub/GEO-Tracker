// 서식/숫자 변환 공통 헬퍼. 백엔드의 Decimal 필드는 JSON에서 문자열("12.340")로 오므로 항상
// toNumber()를 거친 뒤 계산/표시한다.

export function toNumber(value) {
  if (value === null || value === undefined || value === "") return null;
  const n = Number(value);
  return Number.isNaN(n) ? null : n;
}

export function formatPercent(value, { digits = 1, fallback = "–" } = {}) {
  const n = toNumber(value);
  if (n === null) return fallback;
  return `${n.toFixed(digits)}%`;
}

export function formatDecimal(value, { digits = 1, fallback = "–" } = {}) {
  const n = toNumber(value);
  if (n === null) return fallback;
  return n.toFixed(digits);
}

// 상단 카드 등의 delta <span class="delta"> 엘리먼트에 값을 반영한다.
// delta가 null/undefined면 "이전 주 데이터 없음"을 무채색으로 표시한다(작업 지시 3번).
// positiveIsGood=false면 부호 해석을 뒤집는다(예: 순위는 숫자가 작을수록 좋음).
export function applyDelta(el, delta, { suffix = "", positiveIsGood = true, noDataText = "이전 주 데이터 없음" } = {}) {
  if (!el) return;
  const n = toNumber(delta);
  el.classList.remove("up", "down");
  if (n === null) {
    el.textContent = noDataText;
    el.style.color = "var(--muted)";
    el.style.fontWeight = "700";
    return;
  }
  el.style.color = "";
  el.style.fontWeight = "";
  const sign = n > 0 ? "+" : "";
  const isGood = n === 0 ? null : positiveIsGood ? n > 0 : n < 0;
  if (isGood === true) el.classList.add("up");
  else if (isGood === false) el.classList.add("down");
  el.textContent = `${sign}${formatDecimal(n)}${suffix} WoW`;
}

export function escapeHtml(value) {
  if (value === null || value === undefined) return "";
  return String(value)
    .replaceAll("&", "&amp;")
    .replaceAll("<", "&lt;")
    .replaceAll(">", "&gt;")
    .replaceAll('"', "&quot;")
    .replaceAll("'", "&#39;");
}

export function formatWeekLabel(week) {
  if (!week) return "–";
  const match = /^(\d{4})-W(\d{2})$/.exec(week);
  if (!match) return week;
  return `${match[1]}년 ${Number(match[2])}주차`;
}

const SENTIMENT_LABEL = { positive: "긍정", neutral: "중립", negative: "부정" };

export function sentimentLabel(sentiment) {
  return SENTIMENT_LABEL[sentiment] || sentiment;
}

const STATUS_LABEL = { pending: "대기", running: "실행 중", success: "성공", failed: "실패" };

export function executionStatusLabel(status) {
  return STATUS_LABEL[status] || status;
}
