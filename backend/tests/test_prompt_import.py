"""엑셀 업로드로 프롬프트를 대량 등록하는 기능 — app/services/prompt_import_service.py."""

from __future__ import annotations

import io

import openpyxl
import pytest
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models.enums import BrandType, FunnelIntent, Language, PromptPhrasing, PromptSource, Target
from app.models.prompt import Prompt
from app.services.prompt_import_service import PromptImportError, import_prompts_from_excel

_HEADER = [
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


def _build_xlsx(rows: list[list[object]]) -> bytes:
    wb = openpyxl.Workbook()
    ws = wb.active
    ws.append(_HEADER)
    for row in rows:
        ws.append(row)
    buffer = io.BytesIO()
    wb.save(buffer)
    return buffer.getvalue()


class TestImportValidFile:
    def test_creates_two_prompts_per_row(self, db_session: Session) -> None:
        file_bytes = _build_xlsx(
            [
                [
                    "KR",
                    "K-Beauty·화장품",
                    "구분없음",
                    "구분없음",
                    "팀장/관리자",
                    "벤더선정",
                    "비브랜드 롱테일",
                    "물류 파트너 선정 기준",
                    "물류 파트너 선정 기준이 무엇인가요?",
                ]
            ]
        )

        result = import_prompts_from_excel(db_session, file_bytes, "test.xlsx")

        assert result.rows_processed == 1
        assert result.prompts_created == 2

        created = (
            db_session.execute(select(Prompt).where(Prompt.source == PromptSource.EXCEL_IMPORT))
            .scalars()
            .all()
        )
        assert len(created) == 2
        by_phrasing = {p.phrasing: p for p in created}
        assert by_phrasing[PromptPhrasing.SEARCH_QUERY].text == "물류 파트너 선정 기준"
        assert by_phrasing[PromptPhrasing.QUESTION].text == "물류 파트너 선정 기준이 무엇인가요?"
        # 같은 원본 행에서 나온 두 문구는 같은 topic_group으로 묶여야 한다.
        assert by_phrasing[PromptPhrasing.SEARCH_QUERY].topic_group == "test.xlsx:2"
        assert by_phrasing[PromptPhrasing.QUESTION].topic_group == "test.xlsx:2"
        assert by_phrasing[PromptPhrasing.QUESTION].language == Language.KO
        assert by_phrasing[PromptPhrasing.QUESTION].target == Target.MANAGER
        assert by_phrasing[PromptPhrasing.QUESTION].funnel_intent == FunnelIntent.VENDOR_SELECTION
        assert by_phrasing[PromptPhrasing.QUESTION].brand_type == BrandType.NON_BRAND_LONGTAIL
        assert by_phrasing[PromptPhrasing.QUESTION].industry == "K-Beauty·화장품"
        for p in created:
            assert p.is_active is True
            assert p.source_file == "test.xlsx"

    def test_dash_and_gubun_eobsim_normalize_to_none(self, db_session: Session) -> None:
        """'-'와 '구분없음'은 '값 없음'을 뜻하므로 그대로 저장하지 않고 NULL로 정규화한다."""
        file_bytes = _build_xlsx(
            [
                [
                    "KR",
                    "-",
                    "구분없음",
                    "구분없음",
                    "공통",
                    "정보탐색",
                    "자사 브랜드",
                    "첼로스퀘어란 무엇인가",
                    "첼로스퀘어가 무엇인가요?",
                ]
            ]
        )

        import_prompts_from_excel(db_session, file_bytes, "own.xlsx")

        created = (
            db_session.execute(select(Prompt).where(Prompt.source == PromptSource.EXCEL_IMPORT))
            .scalars()
            .all()
        )
        assert all(p.industry is None for p in created)
        assert all(p.service_line is None for p in created)
        assert all(p.brand_type == BrandType.OWN_BRAND for p in created)


class TestImportValidationFailsAllOrNothing:
    def test_unknown_target_value_aborts_without_creating_anything(
        self, db_session: Session
    ) -> None:
        file_bytes = _build_xlsx(
            [
                [
                    "KR",
                    "K-Beauty·화장품",
                    "구분없음",
                    "구분없음",
                    "알수없는직급",  # 매핑 불가능한 값
                    "벤더선정",
                    "비브랜드 롱테일",
                    "V1",
                    "V2?",
                ]
            ]
        )

        with pytest.raises(PromptImportError) as exc_info:
            import_prompts_from_excel(db_session, file_bytes, "bad.xlsx")

        assert len(exc_info.value.row_errors) == 1
        assert exc_info.value.row_errors[0].row_number == 2
        remaining = (
            db_session.execute(select(Prompt).where(Prompt.source == PromptSource.EXCEL_IMPORT))
            .scalars()
            .all()
        )
        assert remaining == []

    def test_wrong_header_rejected(self, db_session: Session) -> None:
        wb = openpyxl.Workbook()
        ws = wb.active
        ws.append(["엉뚱한", "헤더"])
        buffer = io.BytesIO()
        wb.save(buffer)

        with pytest.raises(PromptImportError):
            import_prompts_from_excel(db_session, buffer.getvalue(), "bad_header.xlsx")

    def test_empty_row_is_skipped_silently(self, db_session: Session) -> None:
        file_bytes = _build_xlsx(
            [
                [None] * 9,
                [
                    "KR",
                    "K-Beauty·화장품",
                    "구분없음",
                    "구분없음",
                    "실무자",
                    "정보탐색",
                    "비브랜드 롱테일",
                    "V1",
                    "V2?",
                ],
            ]
        )

        result = import_prompts_from_excel(db_session, file_bytes, "with_blank_row.xlsx")

        assert result.rows_processed == 1
        assert result.prompts_created == 2
