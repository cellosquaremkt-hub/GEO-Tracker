import enum


class Target(enum.StrEnum):
    C_LEVEL = "c-level"
    MANAGER = "manager"
    PRACTITIONER = "practitioner"
    JUNIOR = "junior"
    SELLER = "seller"
    COMMON = "common"


class Priority(enum.StrEnum):
    HIGH = "High"
    MEDIUM = "Medium"
    LOW = "Low"


class Language(enum.StrEnum):
    KO = "ko"
    EN = "en"


class FunnelIntent(enum.StrEnum):
    """구매 퍼널 단계 — docs/metrics.md 참조 필요 시 이 필드도 함께 갱신한다."""

    PROBLEM_AWARENESS = "problem_awareness"
    SOLUTION_COMPARISON = "solution_comparison"
    VENDOR_SELECTION = "vendor_selection"
    INFO_SEARCH = "info_search"


class BrandType(enum.StrEnum):
    """프롬프트가 브랜드를 어떻게 다루는지 — OWN_BRAND는 브랜드명을 직접 묻는 질문이라 SOV
    집계(분자/분모)에서 항상 제외한다(aggregation.py, report_service.py 참조). 이 프롬프트를
    일반 언급 데이터와 합치면 자사 브랜드 SOV가 구조적으로 100%에 가깝게 부풀려진다."""

    NON_BRAND_LONGTAIL = "non_brand_longtail"
    CATEGORY_REPRESENTATIVE = "category_representative"
    COMPETITIVE_COMPARISON = "competitive_comparison"
    OWN_BRAND = "own_brand"


class PromptPhrasing(enum.StrEnum):
    """같은 주제를 검색어형(V1)으로 물을지 질문형(V2)으로 물을지 — topic_group으로 짝을 찾아
    같은 주제의 두 문구가 결과에 미치는 차이를 비교할 수 있다."""

    SEARCH_QUERY = "search_query"
    QUESTION = "question"


class PromptSource(enum.StrEnum):
    """이 프롬프트가 어떻게 생성됐는지 — EXCEL_IMPORT는 관리자가 손으로 하나씩 등록한 게 아니라
    엑셀 업로드로 대량 생성됐다는 꼬리표다(source_file/imported_at과 함께 조회)."""

    MANUAL = "manual"
    EXCEL_IMPORT = "excel_import"


class ExecutionStatus(enum.StrEnum):
    PENDING = "pending"
    RUNNING = "running"
    SUCCESS = "success"
    FAILED = "failed"


class Sentiment(enum.StrEnum):
    POSITIVE = "positive"
    NEUTRAL = "neutral"
    NEGATIVE = "negative"
