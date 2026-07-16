# API 명세 요약

이 프로젝트는 Flask라 FastAPI처럼 코드에서 OpenAPI 스펙/Swagger UI를 자동 생성하지 않는다 —
참고 프로젝트(20260709, FastAPI)의 `/docs`/`/redoc` 링크는 이 프로젝트에는 없다. 이 문서가 API
계약의 단일 진실 원천(SSOT)이다 — 정확한 요청/응답 필드는 `app/schemas/*.py`(Pydantic 모델,
FastAPI 시절과 동일하게 재사용됨)를 함께 참조한다.

## 1. 인증

- **공개 엔드포인트**: 인증 없이 호출 가능(대시보드 조회용 — 프론트엔드 메인 화면이 쓰는
  엔드포인트 대부분).
- **관리자 엔드포인트**: 요청 헤더에 `X-Admin-Api-Key: <ADMIN_API_KEY>`가 필요하다(`.env`의
  `ADMIN_API_KEY`, `app/core/security.py`의 `require_admin_api_key` 데코레이터). 없거나
  틀리면 `401`.
- 아래 표의 "인증" 열이 "관리자"인 엔드포인트가 여기에 해당한다.

## 2. 엔드포인트 표

| 메서드 | 경로 | 인증 | 설명 | 주요 쿼리/바디 파라미터 |
|---|---|---|---|---|
| GET | `/health` | 공개 | 헬스체크 (`{"status": "ok"}`) | — |
| GET | `/dashboard/summary` | 공개 | 대시보드 상단 카드 (AI SOV 합산, 순위, 전주 대비 델타, 부정 언급 수) | `week`(생략 시 현재 주) |
| GET | `/trends` | 공개 | 브랜드별 주차별 SOV 시계열 (Position Tracking 차트) | `weeks`(기본 8, 1~52), `week`(종료 주차, 생략 시 현재 주) |
| GET | `/brands/{brand_id}/overview` | 공개 | 특정 브랜드의 이번 주 채널별(SOV/언급/인용 페이지) 브레이크다운 | `week` |
| GET | `/prompts` | 공개 | 프롬프트 목록 + 필터 | `intent`, `target`, `priority`, `language`, `is_active` |
| GET | `/prompts/{prompt_id}/detail` | 공개 | 특정 프롬프트의 특정 주 실행 전문(채널별 응답+하이라이트+감정+인용) | `week` |
| GET | `/reports/weekly` | 공개 | 주간 리포트(실행 건수, 취약/경쟁사 우위 프롬프트, 감정 분포) | `week` |
| GET | `/export/csv` | 공개 | mention 원본을 CSV로 내보내기 | `week` |
| GET | `/llm-providers` | 관리자 | 측정 채널(LLM 프로바이더) 목록 | — |
| PUT | `/llm-providers/{provider_id}` | 관리자 | 채널 활성/비활성 토글, 모델명 변경 (`name`은 수정 불가) | body: `is_active`, `model_string`, `supports_web_search` |
| GET | `/brands` | 관리자 | 브랜드 전체 목록(별칭/도메인 포함) | — |
| GET | `/brands/{brand_id}` | 관리자 | 브랜드 단건 조회 | — |
| POST | `/brands` | 관리자 | 브랜드 생성 (이름/도메인 중복 시 `409`) | body: `name`, `is_own`, `aliases[]`, `domains[]` |
| PUT | `/brands/{brand_id}` | 관리자 | 브랜드 수정 — `aliases`/`domains`는 값이 오면 전체 교체, 생략하면 기존 유지 | body: `name`, `is_own`, `aliases[]`, `domains[]` |
| POST | `/prompts` | 관리자 | 프롬프트 생성. `supersedes_id` 지정 시 새 버전(`version+1`)으로 생성 (텍스트 수정 API는 없음 — 불변 규칙) | body: `text`, `intent`, `target`, `priority`, `language`, `supersedes_id?` |
| PUT | `/prompts/{prompt_id}/deactivate` | 관리자 | 프롬프트 비활성화 (`is_active=false`) | — |
| GET | `/batch-config` | 관리자 | 배치 REPEAT_COUNT 설정 조회 | — |
| PUT | `/batch-config` | 관리자 | REPEAT_COUNT 변경(1~20) | body: `repeat_count` |
| POST | `/runs/trigger` | 관리자 | **이번 주 배치의 PENDING execution_run을 만들고 즉시 반환한다(CLI 실행 없음)** — 실제 실행은 별도 worker 데몬이 백그라운드에서 처리(§2.5, 아래 참고) | — |
| POST | `/runs/{batch_id}/resume` | 관리자 | FAILED 잡만 PENDING으로 되돌리고 즉시 반환한다(마찬가지로 CLI 실행 없음) | — |
| GET | `/runs/{batch_id}/status` | 관리자 | 배치 상태(pending/running/success/failed 건수, 누적 비용) — 프론트엔드가 이 엔드포인트를 폴링해 진행 상황을 표시한다 | — |

## 2.1 `/runs/trigger`, `/runs/{batch_id}/resume`는 즉시 응답한다 (중요한 계약 변경)

참고 프로젝트(FastAPI+SQLite)에서는 이 두 엔드포인트가 배치 실행이 **끝날 때까지 기다린** 뒤
최종 결과(`success`/`failed` 건수)를 응답했다. 이 프로젝트(Flask+PostgreSQL)는 그 반대다:

- Gunicorn 워커 프로세스 안에서 CLI 서브프로세스를 실행하면 워커 재활용/재시작 시 실행 중이던
  작업이 소리 없이 사라지고, 프로바이더별 동시 실행 상한이 워커 수만큼 곱해지는 문제가 있다
  (`docs/deployment.md` §아키텍처 참조).
- 그래서 이 두 엔드포인트는 execution_run을 **PENDING 상태로 만들기만 하고 즉시 반환한다.**
  반환된 `pending`/`running`/`success`/`failed` 값은 "방금 만든/되돌린 잡의 개수"일 뿐 최종
  결과가 아니다.
- 실제 실행(CLI 호출, 파싱, 집계)은 완전히 분리된 별도 프로세스인 `app/worker/daemon.py`가
  전담한다. 프론트엔드는 `GET /runs/{batch_id}/status`를 2~3초 간격으로 폴링해
  `pending + running == 0`이 될 때까지 기다린 뒤 완료로 간주한다
  (`frontend/js/api.js`의 `pollBatchUntilDone()` 참조).

## 3. 대표 응답 예시

### `GET /dashboard/summary`

```json
{
  "week": "2026-W29",
  "previous_week": "2026-W28",
  "total_sov": "50.000",
  "rank": 1,
  "total_ranked_entities": 6,
  "sov_delta": null,
  "negative_mention_count": 0
}
```

`sov_delta`가 `null`이면 "이전 주 데이터 없음"을 뜻한다(프론트엔드는 이 값을 그렇게 표기한다) —
0으로 채우면 "변화가 없었다"는 잘못된 신호가 된다(docs/metrics.md §5 null 의미 요약과 같은 원칙).

### `POST /runs/trigger` (트리거 직후 — §2.1 참조, 아직 실행 전이라 pending이 채워져 있다)

```json
{
  "batch_id": "2026-W29",
  "pending": 90,
  "running": 0,
  "success": 0,
  "failed": 0,
  "total_cost_usd": "0"
}
```

### `GET /runs/{batch_id}/status` (worker 데몬이 완료한 뒤 — 실측 화면)

```json
{
  "batch_id": "2026-W29",
  "pending": 0,
  "running": 0,
  "success": 90,
  "failed": 0,
  "total_cost_usd": "0.369000"
}
```

### 오류 응답 공통 형식

FastAPI 기본 형식과 동일하게 `{"detail": "사람이 읽을 수 있는 오류 메시지"}`를 쓴다 — Flask에는
이 자동 변환이 없어 각 라우트가 명시적으로 이 형태로 응답하고, Pydantic 검증 실패는
`app/main.py`의 전역 `errorhandler(ValidationError)`가 `422`로 통일해 반환한다.
`BatchTooLargeError`(배치 시작 자체 거부)는 `/runs/trigger`에서만 `400`으로 나타난다.

## 4. 변경 이력

| 날짜 | 변경 내용 |
|---|---|
| 2026-07-13 | 참고 프로젝트(20260709) STEP 7: 최초 작성 |
| 2026-07-15 | Flask+PostgreSQL 재개발: §2.1 트리거/재개 즉시 응답 계약 추가, `/batch-config` 표에 추가, Swagger UI 링크 제거(Flask는 자동 생성 안 함), 오류 응답 형식을 Flask 기준으로 갱신 |
