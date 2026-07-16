// 여러 화면(대시보드 Top keywords, 리포트 감정 분석, 브랜드 인용 출처 분석)이 공통으로 쓰는
// "이번 주 프롬프트별 상세(언급/감정/인용) 전체"를 한 번만 모아서 캐시한다.
//
// 백엔드에 "주간 전체 언급 집계" 같은 별도 엔드포인트가 없으므로(작업 지시: API 시그니처 변경
// 금지), 활성 프롬프트 목록(GET /prompts) + 프롬프트별 상세(GET /prompts/{id}/detail)를 N+1로
// 모아서 프론트에서 직접 펼친다. 활성 프롬프트가 수십 개 수준인 MVP 규모를 전제로 한다
// (plan.md — "프롬프트 수백~수천 조합"까지 커지면 백엔드에 집계 엔드포인트를 추가하는 편이
// 낫다 — 지금은 그 정도 규모가 아니다).
import * as api from "./api.js";

const cache = new Map();

export async function loadWeekMentions(week) {
  const key = week || "__current__";
  if (cache.has(key)) return cache.get(key);

  const promise = (async () => {
    const prompts = await api.listPrompts({ is_active: true });
    const details = await Promise.all(
      prompts.map((p) => api.getPromptDetail(p.id, week).catch(() => null))
    );

    const rows = [];
    prompts.forEach((prompt, index) => {
      const detail = details[index];
      if (!detail) return;
      for (const exec of detail.executions) {
        for (const mention of exec.mentions) {
          rows.push({
            promptId: prompt.id,
            promptText: prompt.text,
            intent: prompt.intent,
            providerId: exec.llm_provider_id,
            providerName: exec.llm_provider_name,
            executionRunId: exec.execution_run_id,
            status: exec.status,
            brandId: mention.brand_id,
            brandName: mention.brand_name,
            mentionOrder: mention.mention_order,
            sentiment: mention.sentiment,
            sentimentEvidence: mention.sentiment_evidence,
          });
        }
      }
    });

    return { prompts, details, rows };
  })();

  cache.set(key, promise);
  return promise;
}

export function clearWeekDataCache() {
  cache.clear();
}
