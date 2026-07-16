# 백로그

지금 스코프 밖이지만 나중에 검토할 가치가 있는 항목들. 우선순위나 일정은 정해져 있지 않다 —
착수하게 되면 이 목록에서 지우고 해당 작업으로 옮긴다.

## GA4 AI 유입 연동

Google Analytics 4에서 "AI 챗봇 경유 유입"으로 추정되는 리퍼러(예: `chat.openai.com`,
`claude.ai`, `gemini.google.com` 등)를 집계해, 이 서비스가 CLI로 측정하는 AI SOV와 실제 웹사이트
유입 데이터를 나란히 비교하는 기능. 현재는 순수 언급/인용 측정만 하고 실제 트래픽 전환은 보지
않는다 — GA4 Data API 연동이 필요하고, 새 어댑터 레이어가 아니라 별도 통합이 될 것이다.

## 콘텐츠 개선 권고

취약 프롬프트(주간 리포트의 "취약 프롬프트" 섹션 — 미노출/부정 언급)에 대해, 단순히 "이
프롬프트가 취약하다"는 진단을 넘어 "어떤 콘텐츠를 보강하면 좋을지"까지 제안하는 기능. LLM
judge를 활용해 경쟁사가 우위인 프롬프트의 응답과 우리 브랜드가 언급된 응답을 비교 분석하는
방식이 유력한 접근으로 보인다.

## 알림/협업 기능

배치 실패(`failed > 0`), SOV 급락, 신규 경쟁사 진입 등의 이벤트를 Slack/이메일로 알리는 기능.
현재는 관리자가 직접 `GET /runs/{batch_id}/status`나 대시보드를 확인해야 안다 — 수동 확인
의존도가 높다.

## LLM 판정 기반 추천 순위(rank) 고도화

`avg_rank`(mention_order 평균)는 텍스트 내 등장 순서의 근사치일 뿐 진짜 추천 강도가 아니다
(docs/metrics.md §2의 알려진 한계). 별도 LLM judge가 응답 전문을 읽고 "이 답변에서 브랜드들을
추천 강도 순으로 정렬하라"는 방식으로 `judged_rank`를 산출하는 것을 검토한다. 도입 시
`mention` 테이블에 `judged_rank` 컬럼을 추가하고, 대시보드 기본값을 `judged_rank` 기반으로
전환하되 `avg_rank`는 하위 호환을 위해 유지한다.

## React 전환

현재 프론트엔드는 빌드 도구 없는 정적 파일 + 브라우저 네이티브 ES 모듈이다(CLAUDE.md). 화면
수가 늘고 상태 관리가 복잡해지면(예: 더 세밀한 실시간 배치 진행률 표시, 복잡한 폼 검증) React 등
프레임워크 도입을 재검토한다. 지금 시점에는 화면 수와 복잡도가 정적 파일 구조로 충분히 감당
가능하다고 판단해 보류한다.

## API 키 확보 시 SDK 어댑터 복귀 + Perplexity 재활성화

회사 사정이 풀려 각 AI사의 API 키를 다시 받을 수 있게 되면:

1. 참고 프로젝트(`C:\자료\작업중\20260709`, 보존됨)의 `backend/app/llm_clients/legacy/`에서
   4개 SDK 어댑터(OpenAI/Gemini/Anthropic/Perplexity)를 이 프로젝트로 **새로 포팅**한다 — 이
   Flask 재개발에서는 그 어댑터들을 처음부터 이식하지 않았으므로(`app/llm_clients/factory.py`
   참조, CLI 3종만 등록되어 있음), "매핑만 되돌리면" 되는 것이 아니라 async→sync 변환을 포함한
   포팅 작업이 새로 필요하다.
2. `app/llm_clients/factory.py`의 `_ADAPTER_CLASSES`에 포팅한 어댑터들을 등록한다.
3. `llm_provider.is_active`를 해당 프로바이더들에 대해 `True`로 되돌린다(seed 데이터 또는 관리
   API `PUT /llm-providers/{id}`) — 레거시 프로바이더 행 자체는 `app/db/seed.py`에 `is_active=
   False`로 이미 보존되어 있다(과거 데이터 조회 호환용, docs/erd.md 참조).
4. `app/services/sentiment.py`에 `LLMSentimentClassifier`(OpenAI 기반)를 포팅하고
   `get_default_sentiment_classifier()`의 분기를 되살린다(docs/metrics.md §7.3.1).
5. Perplexity는 전용 CLI가 없어 제외됐던 것이므로, API 키 확보 시 곧바로 재활성화 대상이다.
6. `docs/metrics.md` §7.2(Perplexity 제외 한계)와 §7.1(CLI proxy 한계)을 갱신해 "SDK 채널이
   다시 추가됨"을 반영한다 — 두 세대(CLI vs SDK) 데이터가 같은 `weekly_snapshot`에 섞이게 되는
   시점의 해석 주의사항을 추가한다.
7. `docs/llm_clis.md`는 삭제하지 않고 유지한다(CLI 채널이 완전히 사라지는 것은 아니고 SDK와
   병행 운영될 가능성이 높음).

## Docker 사용 가능 환경으로 전환 시

Ubuntu 서버에서 Docker를 쓸 수 있게 되면 `deploy/optional/docker-compose.yml`(PostgreSQL
컨테이너 정의)로 전환할 수 있다 — DB 접속 정보(`DATABASE_URL`)만 컨테이너 쪽으로 바꾸면 되고,
`app/db/engine.py`/모델/마이그레이션 코드는 이미 순수 PostgreSQL 기준이라 변경이 필요 없다. 웹
앱/worker 데몬도 각각 컨테이너화할 수 있지만, 그 경우 worker 데몬 컨테이너가 "정확히 1개
레플리카"로 고정되도록 오케스트레이션 설정(예: Docker Compose의 `deploy.replicas: 1`, 또는
Kubernetes Deployment의 `replicas: 1` + `strategy: Recreate`)을 반드시 명시해야 한다
(migration_flask_postgres.md §2.3의 단일 인스턴스 전제가 깨지지 않도록).

## worker 데몬 동시성 모델을 Celery+Redis로 전환

현재 `app/worker/daemon.py`는 단일 프로세스 안의 프로바이더별 `ThreadPoolExecutor` + DB 폴링
루프로 동시성을 제어한다. 배치 규모가 훨씬 커지거나(예: 프롬프트/브랜드 수가 수십 배로 늘어남),
worker를 여러 서버에 분산해야 하는 시점이 오면 Celery+Redis(또는 유사한 분산 태스크 큐)로
전환을 검토한다 — 그 경우 `app/services/`의 순수 로직(집계/파싱/매칭)은 트리거 계층에 의존하지
않게 작성되어 있어 그대로 재사용 가능하다(CLAUDE.md 코딩 컨벤션). 지금 배치 규모(프롬프트 x
프로바이더 x REPEAT_COUNT 수십~수백 건/주)에서는 이 정도 인프라가 과하다고 판단해 보류한다.

## 프로바이더별 동시성 세분화

현재 `*_CONCURRENCY_LIMIT`(CLAUDE_CODE/CODEX/GEMINI_CLI)은 고정값 설정이다. 실측 경험이
쌓이면 시간대별/요일별로 다른 상한을 적용하거나, 프로바이더의 실시간 rate limit 잔여량을 조회할
수 있는 API가 생기면 그에 맞춰 동적으로 조정하는 방안을 검토한다.

## 변경 이력

| 날짜 | 변경 내용 |
|---|---|
| 2026-07-13 | 참고 프로젝트(20260709) STEP 7: 최초 작성 |
| 2026-07-15 | Flask+PostgreSQL 재개발: "PostgreSQL 복귀" 항목을 "Docker 전환 시" 항목으로 교체(이미 Postgres로 이전 완료), SDK 어댑터 복귀 절차를 "새로 포팅 필요"로 정정, worker 데몬 Celery+Redis 전환 항목 추가 |
