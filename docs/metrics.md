# 지표 정의 (Single Source of Truth)

이 문서는 GEO Weekly Tracker의 모든 지표(AI SOV, avg_rank, 감정 분포, Citation Share)에 대한
**단일 진실 원천(SSOT)**이다. 코드에서 지표 계산 로직을 작성/수정할 때는 이 문서를 먼저 확인하고,
문서와 다르게 구현해야 할 이유가 있으면 코드보다 이 문서를 먼저 갱신한다 (CLAUDE.md 참조).

계산 로직은 `backend/app/services/`에 트리거 계층(Flask 라우트, worker 데몬)에 종속되지 않는
순수 로직으로 구현한다(CLAUDE.md 코딩 컨벤션).

## 0. 스코프 정의

모든 지표는 아래 두 가지 스코프 중 하나에 대해 계산된다.

- **주간 전체 스코프**: 특정 `week_label`에 속한 모든 `execution_run` (모든 LLM 프로바이더 합산).
  `weekly_snapshot.llm_provider_id = NULL`인 행에 해당한다.
- **주간 x 프로바이더 스코프**: 특정 `week_label` + 특정 `llm_provider_id`에 속한 `execution_run`.
  `weekly_snapshot.llm_provider_id`가 채워진 행에 해당한다.

이번 MVP에서는 배치 1회 = 주 1회이므로 `execution_run.batch_id`와 `weekly_snapshot.week_label`은
동일한 값 체계(ISO 8601 주차 표기, 예: `"2026-W28"`)를 공유한다. 즉 특정 `week_label`의 스코프는
`batch_id = week_label`인 `execution_run` 집합과 같다.

아래 모든 정의에서:

- **R** = 해당 스코프에 속하고 `status = 'success'`인 `execution_run`의 집합.
- **total_runs** = `|R|` (스코프의 분모 기록용 카운트. `status != 'success'`인 실행은 응답 내용이
  없거나 신뢰할 수 없으므로 모든 지표 계산에서 제외한다).
- 브랜드 집합 **B** = `brand` 테이블의 전체 행 (자사 + 경쟁사 모두 포함).

## 1. AI SOV (Share of Voice) — North Star 지표

특정 브랜드 `b`가, 추적 중인 모든 브랜드의 총 언급량 대비 얼마나 많이 언급되는지를 나타낸다.

```
mention_count(b) = R 안에서 brand_id = b인 mention row 개수
                  (execution_run당 브랜드당 최대 1행이므로 = 해당 브랜드가 언급된 run 수)

total_mentions   = sum( mention_count(b) for b in B )   # 모든 브랜드 언급량의 합

sov(b) = mention_count(b) / total_mentions * 100         (total_mentions > 0일 때)
sov(b) = 0                                                (total_mentions = 0일 때, 관례)
```

- **분자**: 브랜드 `b`가 언급된 run 수.
- **분모**: 스코프 내 모든 브랜드의 언급 합계 (경쟁사 포함 — "목소리 점유율"이므로 전체 발화량 대비
  비중이다).
- `total_mentions = 0`(스코프 내 어떤 브랜드도 전혀 언급되지 않음)인 극단적인 경우 0으로
  나누기를 피하기 위해 SOV를 0으로 정의한다. `weekly_snapshot.sov`는 이 이유로 `NOT NULL`이다.

## 2. avg_rank — mention_order 근사치 (한계 명시)

**"등장 순서(mention_order)"와 "추천 순위(rank)"는 다른 개념이다.** MVP에서는 LLM 응답 텍스트 내에
브랜드명/별칭이 처음 등장한 위치(`mention.mention_order`, 1부터 시작)만 실측하고, 이를 진짜 추천
순위의 **근사치**로 사용한다.

```
avg_rank(b) = mean( mention_order for m in mention where m.brand_id = b and m.execution_run_id in R )
avg_rank(b) = NULL   (mention_count(b) = 0일 때 — 즉 해당 브랜드가 스코프 내에서 한 번도 언급되지
                       않았을 때. 빈 집합의 평균은 정의되지 않으므로 0이나 임의의 큰 값으로 대체하지
                       않고 NULL로 남긴다.)
```

### 알려진 한계 (반드시 인지할 것)

- `mention_order`는 텍스트 내 물리적 등장 순서일 뿐, LLM이 실제로 그 브랜드를 "더 추천"한다는
  의미가 아니다. 예: 목록형 답변에서 알파벳순/무작위 순서로 브랜드를 나열하면 등장 순서와 추천
  강도가 무관할 수 있다. 부정적으로 언급된 브랜드가 먼저 등장할 수도 있다.
- 따라서 `avg_rank`는 "낮을수록 좋다"는 해석을 대시보드에 노출할 때 반드시 근사치임을 명시해야
  한다.
- **LLM 판정 기반의 진짜 추천 순위 추출(예: 별도 LLM judge가 응답을 읽고 "이 답변에서 브랜드들을
  추천 강도 순으로 정렬하라"는 방식)은 백로그다.** 도입 시 `mention` 테이블에 별도 컬럼(예:
  `judged_rank`)을 추가하고, `avg_rank`는 하위 호환을 위해 유지하되 대시보드 기본값을
  `judged_rank` 기반으로 전환한다.

## 3. 감정 분포 (sentiment_positive_pct / neutral / negative)

브랜드가 언급된 맥락의 감정을 3분류로 집계한다.

```
sentiment_count(b, s) = R 안에서 brand_id = b, sentiment = s인 mention row 개수   (s ∈ {positive, neutral, negative})

sentiment_<s>_pct(b) = sentiment_count(b, s) / mention_count(b) * 100   (mention_count(b) > 0일 때)
sentiment_<s>_pct(b) = NULL                                             (mention_count(b) = 0일 때)
```

- 분모는 **해당 브랜드의 총 언급 수**(`mention_count(b)`)다. 스코프 전체 실행 수(`total_runs`)가
  아니다 — 언급되지 않은 run은 감정 판정 대상 자체가 없기 때문이다.
- 세 비율의 합은 (부동소수점 오차를 제외하면) 100이다.
- `mention_count(b) = 0`이면 세 값 모두 NULL이다. 0/0/0으로 채우면 "완전히 중립적"이라는 잘못된
  신호를 주므로 금지한다.

## 4. Citation Share (citation_share_pct)

브랜드가 실제로 인용(출처 URL로 링크)된 비중.

```
total_citations   = R 안의 citation row 개수 (스코프 전체, 브랜드 매칭 여부 무관)
brand_citations(b) = R 안에서 matched_brand_id = b인 citation row 개수

citation_share_pct(b) = brand_citations(b) / total_citations * 100   (total_citations > 0일 때)
citation_share_pct(b) = NULL                                          (total_citations = 0일 때)
```

- `citation.matched_brand_id`가 NULL인 인용(외부 매체, 뉴스 등 추적 브랜드가 아닌 출처)은
  `total_citations`(분모)에는 포함되지만 어떤 브랜드의 `brand_citations`(분자)에도 포함되지 않는다.
  즉 "추적 브랜드가 아닌 출처가 인용을 얼마나 잠식하는지"도 `total_citations - sum(brand_citations)`
  로 유도할 수 있다.
- 도메인 매칭은 `brand_domain` 테이블 기준이며, 별칭 기반 매칭이 아니라 정확한 도메인 매칭이다.

## 5. null 의미 요약

| 필드 | null의 의미 |
|---|---|
| `weekly_snapshot.sov` | (NOT NULL) — 언급이 전혀 없는 주는 0으로 정의 |
| `weekly_snapshot.avg_rank` | 해당 브랜드가 스코프 내에서 한 번도 언급되지 않음 |
| `weekly_snapshot.sentiment_positive/neutral/negative_pct` | 해당 브랜드가 스코프 내에서 한 번도 언급되지 않음 |
| `weekly_snapshot.citation_share_pct` | 스코프 내에 인용(citation) 자체가 하나도 없음 |
| `execution_run.raw_response` | 아직 실행되지 않았거나(`status=pending/running`) 실패함(`status=failed`) |
| `citation.matched_brand_id` | 인용 URL의 도메인이 `brand_domain`에 등록된 어떤 브랜드와도 매칭되지 않음 |

## 6. 데이터 보존 / 저작권 운영 방침

이 서비스는 사내 전용 B2B 브랜드 모니터링 대시보드다(외부 공개 서비스가 아니고, LLM 응답 원문을
제3자에게 재배포·재게시하지 않는다). 이 전제 위에서 아래 방침을 확정한다. 법무팀의 정식 검토를
거친 것은 아니므로, 서비스 성격이 바뀌거나(예: 외부 고객 대상 제품화) 데이터 보관량이 문제가 되면
재검토한다 — 재검토가 필요해진 시점의 담당자가 이 절을 갱신한다.

- **`execution_run.raw_response` 보관 기간: 무기한 보존, 자동 삭제 배치 없음.** LLM 응답 전문은
  브랜드 매칭/감정 판정/인용 추출의 근거 자료이자, 향후 판정 로직을 개선할 때 재파싱할 유일한
  원본이다. PostgreSQL 테이블 크기가 실제로 문제가 되는 시점(수십만 row 이상 누적 등)이 오면,
  그때 가서 "N개월 이전 raw_response를 별도 아카이브 테이블/파티션으로 이전" 같은 방안을
  검토한다 — 지금은 조기 최적화하지 않는다.
- **LLM 응답의 저작권/재게시 범위: 사내 열람 전용, 외부 재게시 금지.** `raw_response`/
  `sentiment_evidence`는 관리자 인증(`ADMIN_API_KEY`)이 필요한 사내 대시보드/API에서만 열람
  가능하며, 이 프로젝트의 어떤 화면도 이를 공개 인터넷에 노출하거나 제3자에게 전달하는 기능을
  두지 않는다. LLM이 웹 검색 결과나 제3자 콘텐츠를 인용한 응답을 포함하더라도(citation URL 등),
  이 서비스는 그 콘텐츠 자체를 재호스팅하지 않고 URL 참조만 저장한다.
- **대시보드 노출 방침: 원문 그대로 노출(요약/치환 금지), 단 사내망 전용 화면에 한정.**
  `sentiment_evidence` 등 원문 근거를 요약본으로 대체하면 검수자가 실제로 감정 판정이 맞는지
  확인할 수 없게 된다. 따라서 원문을 그대로 노출하되, 이 노출 범위는 위에서 정의한 "사내 열람
  전용" 범위를 벗어나지 않는다.

이 방침이 확정됨에 따라, 이 필드들을 삭제하거나 요약본으로 대체하는 배치 로직은 앞으로도
구현하지 않는다(원본 보존이 정책으로 고정됨).

## 7. 측정 한계 (CLI 기반 측정)

회사 사정으로 각 AI사의 API 키를 발급받을 수 없어, 측정 채널은 구독 좌석 기반 코딩 에이전트
CLI(Claude Code CLI/Codex CLI/Gemini CLI) 호출이다. 이 전제는 위 1~6절의 계산식 자체를 바꾸지
않지만, **입력 데이터(`execution_run`)가 어떻게 만들어지는지에서 비롯되는 아래 한계가 모든 지표의
해석에 적용된다.** 상세 조사 근거는 [docs/llm_clis.md](llm_clis.md) 참조.

### 7.1 코딩 에이전트를 통한 측정은 소비자 챗봇 노출도의 proxy(대리 지표)다

Claude Code/Codex/Gemini CLI는 소비자용 채팅 제품(claude.ai, ChatGPT, Gemini 앱)이 아니라
**코딩 에이전트**다. 같은 기반 모델이라도 코딩 에이전트 컨텍스트(시스템 프롬프트, 사용 가능한
도구 목록, "당신은 코딩 어시스턴트다"류의 역할 설정)에서 나오는 답변은 소비자 챗봇에서 같은
질문을 던졌을 때의 답변과 다를 수 있다. 따라서 이 서비스가 측정하는 AI SOV/avg_rank/감정 분포/
Citation Share는 **"소비자가 실제로 AI에게 물었을 때 이 브랜드가 언급되는 정도"의 근사치(proxy)
이지, 그 자체가 아니다.** 대시보드/리포트에 이 지표를 노출할 때는 반드시 "코딩 에이전트 CLI
기준 측정"이라는 전제를 함께 표기한다.

### 7.2 Perplexity는 측정 대상에서 제외된다

Perplexity는 전용 CLI가 없어 새 측정 채널에서 완전히 제외된다.

### 7.3 CLI별 웹 검색 사용 판정 신뢰도가 다르다

세 CLI는 웹 검색 도구의 기본 활성화 여부와, "실제로 이번 호출에서 검색했는지"를 사후에 확인할
수 있는지가 서로 다르다(docs/llm_clis.md §4 참조).

- Claude Code CLI, Codex CLI: `web_search_used`가 항상 "도구가 허용되어 있었다"는 근사치다 —
  실제 호출 여부의 증거가 아니다.
- Gemini CLI: 일부 버전에서 `stats.tools.google_web_search.count`로 실제 호출 횟수를 신뢰성
  있게 확인할 수 있다.

이 비대칭 때문에 프로바이더별 `web_search_used` 비율을 단순 비교하면 왜곡된다. `web_search_used`
기반 분석(예: "웹 검색을 쓴 답변일수록 인용이 많다")을 할 때는 이 필드의 신뢰도가 프로바이더마다
다르다는 점을 명시해야 한다.

### 7.3.1 감정 분류는 항상 키워드 규칙 기반이다 (OpenAI 키 부재)

회사 사정으로 **OpenAI API 키 자체가 없다.** 이 재개발(Flask+PostgreSQL 전환)에서는 이 사실을
반영해 `app/services/sentiment.py`에 소형 LLM 기반 분류기(`LLMSentimentClassifier`)를 아예
이식하지 않았다 — `get_default_sentiment_classifier()`는 항상 `KeywordRuleSentimentClassifier`
(사전 정의된 긍/부정 단어 목록의 단순 포함 여부 판정)를 반환한다.

- 키워드 규칙 분류기는 문맥/반어법/복합 감정을 이해하지 못하는 명백한 한계가 있다. 3절의
  `sentiment_*_pct` 지표는 이 정확도 한계 위에서 계산된다는 점을 감안해 해석해야 한다.
- API 키를 다시 받으면(`docs/backlog.md`) `LLMSentimentClassifier`를 이식하고
  `get_default_sentiment_classifier()`의 분기를 되살이면 된다.

### 7.4 citation은 항상 본문 URL 정규식 폴백으로 추출된다

세 CLI 모두 구조화된 citation 필드를 반환하지 않는다(`LLMResponse.citations`는 항상 빈 리스트).
`citation` 테이블의 모든 행은 파싱 엔진의 본문 URL 정규식 폴백(`app/services/citation_extraction.py`
`resolve_citations()`)으로 추출된 것이다 — 정규식이 놓치는 인용 형식(예: 마크다운 링크 텍스트
안에 숨겨진 URL, 각주 스타일 참조 등)이 있다면 Citation Share(4절)가 실제보다 낮게 집계될 수
있다.

### 7.5 Claude Code CLI는 사용자 계정 수준의 컨텍스트 오염 위험이 있다 (`--bare` 미사용)

실 CLI 파일럿에서 `--bare` 모드가 구독 좌석 인증(`CLAUDE_CODE_OAUTH_TOKEN`)을 인식하지 못해
매번 인증 실패하는 것을 확인했다 — 인증이 안 되면 측정 자체가 불가능하므로 `--bare`를 빼기로
결정했다(docs/llm_clis.md §1(a) 참조). `CLI_WORKDIR`가 항상 비어있는 전용 디렉터리로 강제되므로
**프로젝트 수준**(이 저장소의 `CLAUDE.md`/`AGENTS.md`) 오염 위험은 여전히 없지만, **사용자 계정
수준**의 스킬/MCP 서버/메모리가 로드될 잔여 위험은 받아들인 한계로 남는다. 즉 Claude Code CLI
채널의 응답은 다른 두 CLI보다 "이 서버 계정에 설정된 것"의 영향을 조금 더 받을 수 있다 —
프로바이더 간 응답을 비교할 때 이 비대칭을 고려한다.

## 8. 변경 이력

| 날짜 | 변경 내용 |
|---|---|
| 2026-07-09 | 최초 작성 (참고 프로젝트, STEP: 데이터 모델 구현) |
| 2026-07-10 | 참고 프로젝트 STEP 6: 측정 채널을 SDK에서 CLI로 전환하며 §7 측정 한계 추가 |
| 2026-07-13 | 참고 프로젝트: §7.5 Claude Code CLI `--bare` 미사용 잔여 위험, §7.3.1 OpenAI 키 부재 확인 |
| 2026-07-13 | 참고 프로젝트 STEP 7: §6 데이터 보존/저작권 방침 확정 |
| 2026-07-15 | Flask+PostgreSQL 재개발: §6 SQLite 파일 언급을 PostgreSQL 기준으로 갱신, §7.3.1을 "이식하지 않음"으로 갱신(코드와 문서 일치) |
