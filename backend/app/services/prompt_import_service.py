"""엑셀 업로드로 프롬프트를 대량 등록하는 기능.

기대하는 열 구성(1행 헤더, 2026-07-28 111 폴더 참고 파일과 동일 스키마):
LN | 산업 | 서비스라인 | 트레이드레인 | 직급(태그) | 퍼널인텐트 | 브랜드성 | V1_검색어형 | V2_질문형

한 행에서 V1(검색어형)과 V2(질문형) 두 개의 프롬프트를 만든다 — 같은 주제를 두 문구로 각각
실행해서 결과를 비교하기 위해서다(CLAUDE.md, prompt.py의 phrasing/topic_group 참조). 이 기능으로
만든 프롬프트는 전부 source=EXCEL_IMPORT로 꼬리표가 붙어 관리자가 직접 등록한 것과 구분된다.

엑셀에는 priority 열이 없으므로 전부 Priority.MEDIUM으로 채운다 — 우선순위가 중요하면 업로드
후 관리자 화면에서 개별 조정한다(전체 재수정 API는 없다 — CLAUDE.md 프롬프트 불변 규칙).

검증은 전부-아니면-전무 방식이다: 한 행이라도 매핑 실패하면 아무 것도 만들지 않고 에러 목록을
반환한다 — 큰 파일을 부분적으로만 반영해서 어떤 게 들어갔는지 헷갈리는 상태를 피하기 위해서다.
"""

from __future__ import annotations

import io
from dataclasses import dataclass
from datetime import UTC, datetime

import openpyxl
from sqlalchemy.orm import Session

from app.models.enums import (
    BrandType,
    FunnelIntent,
    Language,
    Priority,
    PromptPhrasing,
    PromptSource,
    Target,
)
from app.services.prompt_service import create_prompt

_EXPECTED_HEADER = [
    "LN",
    "산업",
    "서비스라인",
    "트레이드레인",
    "직급(태그)",
    "퍼널인텐트",
    "브랜드성",
    "V1_검색어형",
    "V2_질문형",
]

_LANGUAGE_MAP = {"KR": Language.KO, "EN": Language.EN}

_TARGET_MAP = {
    "C-level/임원": Target.C_LEVEL,
    "팀장/관리자": Target.MANAGER,
    "실무자": Target.PRACTITIONER,
    "공통": Target.COMMON,
}

_FUNNEL_INTENT_MAP = {
    "문제인지": FunnelIntent.PROBLEM_AWARENESS,
    "솔루션비교": FunnelIntent.SOLUTION_COMPARISON,
    "벤더선정": FunnelIntent.VENDOR_SELECTION,
    "정보탐색": FunnelIntent.INFO_SEARCH,
}

_BRAND_TYPE_MAP = {
    "비브랜드 롱테일": BrandType.NON_BRAND_LONGTAIL,
    "카테고리 대표성": BrandType.CATEGORY_REPRESENTATIVE,
    "경쟁 비교형": BrandType.COMPETITIVE_COMPARISON,
    "자사 브랜드": BrandType.OWN_BRAND,
}

# 실질적으로 "값 없음"을 뜻하는 표기 — intent 필드 등 자유 텍스트로 그대로 옮기지 않는다.
_BLANK_MARKERS = {"-", "구분없음", ""}


class PromptImportError(Exception):
    """업로드된 엑셀에 매핑 불가능한 값이 있어 아무 것도 만들지 않고 중단할 때."""

    def __init__(self, row_errors: list[RowError]):
        self.row_errors = row_errors
        super().__init__(f"{len(row_errors)}개 행에서 오류가 발견되어 가져오기를 중단했습니다.")


@dataclass(frozen=True)
class RowError:
    row_number: int
    message: str


@dataclass(frozen=True)
class ImportResult:
    source_file: str
    rows_processed: int
    prompts_created: int


@dataclass
class _ParsedRow:
    row_number: int
    language: Language
    industry: str | None
    service_line: str | None
    trade_lane: str | None
    target: Target
    funnel_intent: FunnelIntent
    brand_type: BrandType
    v1_text: str
    v2_text: str


def _clean(value: object) -> str | None:
    text = str(value).strip() if value is not None else ""
    if text in _BLANK_MARKERS:
        return None
    return text


def _parse_workbook(file_bytes: bytes) -> tuple[list[_ParsedRow], list[RowError]]:
    wb = openpyxl.load_workbook(io.BytesIO(file_bytes), data_only=True, read_only=True)
    ws = wb.worksheets[0]
    rows_iter = ws.iter_rows(values_only=True)
    header = next(rows_iter, None)
    if header is None or list(header) != _EXPECTED_HEADER:
        raise PromptImportError(
            [
                RowError(
                    row_number=1,
                    message=(
                        "1행 헤더가 예상 형식과 다릅니다. 다음 순서의 9개 열이어야 합니다: "
                        + ", ".join(_EXPECTED_HEADER)
                    ),
                )
            ]
        )

    parsed: list[_ParsedRow] = []
    errors: list[RowError] = []
    for offset, row in enumerate(rows_iter, start=2):
        if row is None or all(v is None for v in row):
            continue  # 완전히 빈 행은 조용히 건너뛴다.
        ln, industry, service_line, trade_lane, target_raw, funnel_raw, brand_raw, v1, v2 = row[:9]

        language = _LANGUAGE_MAP.get(_clean(ln) or "")
        if language is None:
            errors.append(RowError(offset, f"LN 값 '{ln}'을(를) ko/en으로 매핑할 수 없습니다."))

        target = _TARGET_MAP.get(_clean(target_raw) or "")
        if target is None:
            errors.append(RowError(offset, f"직급(태그) 값 '{target_raw}' 매핑 불가"))

        funnel_intent = _FUNNEL_INTENT_MAP.get(_clean(funnel_raw) or "")
        if funnel_intent is None:
            errors.append(RowError(offset, f"퍼널인텐트 값 '{funnel_raw}' 매핑 불가"))

        brand_type = _BRAND_TYPE_MAP.get(_clean(brand_raw) or "")
        if brand_type is None:
            errors.append(RowError(offset, f"브랜드성 값 '{brand_raw}'을(를) 매핑할 수 없습니다."))

        v1_text = _clean(v1)
        v2_text = _clean(v2)
        if not v1_text:
            errors.append(RowError(offset, "V1_검색어형이 비어 있습니다."))
        if not v2_text:
            errors.append(RowError(offset, "V2_질문형이 비어 있습니다."))

        if language and target and funnel_intent and brand_type and v1_text and v2_text:
            parsed.append(
                _ParsedRow(
                    row_number=offset,
                    language=language,
                    industry=_clean(industry),
                    service_line=_clean(service_line),
                    trade_lane=_clean(trade_lane),
                    target=target,
                    funnel_intent=funnel_intent,
                    brand_type=brand_type,
                    v1_text=v1_text,
                    v2_text=v2_text,
                )
            )
    return parsed, errors


def import_prompts_from_excel(
    session: Session, file_bytes: bytes, source_filename: str
) -> ImportResult:
    parsed_rows, errors = _parse_workbook(file_bytes)
    if errors:
        raise PromptImportError(errors)

    imported_at = datetime.now(UTC)
    created = 0
    for row in parsed_rows:
        topic_group = f"{source_filename}:{row.row_number}"
        intent = row.industry or row.service_line or "미분류"
        for text, phrasing in (
            (row.v1_text, PromptPhrasing.SEARCH_QUERY),
            (row.v2_text, PromptPhrasing.QUESTION),
        ):
            create_prompt(
                session,
                text=text,
                intent=intent,
                target=row.target,
                priority=Priority.MEDIUM,
                language=row.language,
                industry=row.industry,
                service_line=row.service_line,
                trade_lane=row.trade_lane,
                funnel_intent=row.funnel_intent,
                brand_type=row.brand_type,
                phrasing=phrasing,
                topic_group=topic_group,
                source=PromptSource.EXCEL_IMPORT,
                source_file=source_filename,
                imported_at=imported_at,
            )
            created += 1

    return ImportResult(
        source_file=source_filename, rows_processed=len(parsed_rows), prompts_created=created
    )
