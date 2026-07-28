// 여러 화면(대시보드 Top keywords, 리포트 감정 분석, 브랜드 인용 출처 분석)이 공통으로 쓰는
// "이번 주 전체 mention"을 한 번만 모아서 캐시한다.
//
// GET /mentions(백엔드 export_service.fetch_mention_rows 재사용) 한 번으로 그 주의 모든
// mention을 가져온다 — 활성 프롬프트마다 GET /prompts/{id}/detail을 개별 호출하던 N+1 패턴은
// 활성 프롬프트가 702개로 늘어난 뒤(엑셀 업로드 기능 도입) 요청이 큐에 쌓여 리포트/감정 분석/
// 대시보드 로딩이 수십 초씩 걸리는 문제로 이어져 제거했다(2026-07-28 브라우저 검증 중 발견).
import * as api from "./api.js";

const cache = new Map();

export async function loadWeekMentions(week) {
  const key = week || "__current__";
  if (cache.has(key)) return cache.get(key);

  const promise = (async () => {
    const mentions = await api.getMentions(week);
    const rows = mentions.map((m) => ({
      promptId: m.prompt_id,
      promptText: m.prompt_text,
      intent: m.prompt_intent,
      providerName: m.llm_provider_name,
      executionRunId: m.execution_run_id,
      brandId: m.brand_id,
      brandName: m.brand_name,
      mentionOrder: m.mention_order,
      sentiment: m.sentiment,
      sentimentEvidence: m.sentiment_evidence,
    }));

    return { rows };
  })();

  cache.set(key, promise);
  return promise;
}

export function clearWeekDataCache() {
  cache.clear();
}
