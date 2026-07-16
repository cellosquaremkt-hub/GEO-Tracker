// 아주 단순한 뷰 전환 라우터. 빌드 도구가 없으므로 해시 라우팅 없이 그냥 .view 토글만 한다.
// 다른 뷰 모듈들이 서로를 import하며 순환 참조가 생기지 않도록(예: keywords.js ↔ promptDetail.js)
// 네비게이션 로직만 이 파일에 따로 뺐다 — main.js도 이 모듈을 통해 초기 화면을 연다.
const TITLES = {
  dashboard: ["GEO Dashboard", "브랜드 언급, 경쟁사 점유, 추천 순위, 응답 근거를 주 단위로 비교합니다."],
  keywords: ["키워드", "측정 중인 프롬프트 목록입니다. 행을 클릭하면 상세 응답을 볼 수 있습니다."],
  "prompt-detail": ["프롬프트 상세", "채널별 실제 응답, 언급, 감정, 인용을 확인합니다."],
  brands: ["브랜드", "브랜드별 AI Overview와 인용 출처를 확인합니다."],
  reports: ["리포트", "주간 요약과 감정 분석을 확인합니다."],
};

const listeners = new Set();

export function onNavigate(fn) {
  listeners.add(fn);
}

export function navigateTo(viewId) {
  document.querySelectorAll(".view").forEach((el) => el.classList.remove("active"));
  document.querySelector(`#view-${viewId}`)?.classList.add("active");

  const [title, subtitle] = TITLES[viewId] || ["", ""];
  const titleEl = document.querySelector("#pageTitle");
  const subtitleEl = document.querySelector("#pageSubtitle");
  if (titleEl) titleEl.textContent = title;
  if (subtitleEl) subtitleEl.textContent = subtitle;

  // prompt-detail은 사이드바에 없는 하위 화면이라 "키워드" 메뉴를 계속 활성 표시한다.
  const navViewId = viewId === "prompt-detail" ? "keywords" : viewId;
  document.querySelectorAll(".nav button[data-view]").forEach((btn) => {
    btn.classList.toggle("active", btn.dataset.view === navViewId);
  });

  for (const fn of listeners) fn(viewId);
}
