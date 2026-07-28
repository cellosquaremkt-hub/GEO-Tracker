from __future__ import annotations

from sqlalchemy.orm import Session

from app.core.config import settings
from app.models.enums import Language, Priority, Target
from app.models.prompt import Prompt

ADMIN_HEADERS = {"X-Admin-Api-Key": settings.admin_api_key}


class TestAuth:
    def test_create_requires_admin_key(self, client) -> None:
        response = client.post(
            "/prompts",
            json={
                "text": "X",
                "intent": "Test",
                "target": "manager",
                "priority": "Medium",
                "language": "ko",
            },
        )
        assert response.status_code == 401

    def test_deactivate_requires_admin_key(self, client) -> None:
        response = client.put("/prompts/1/deactivate")
        assert response.status_code == 401


class TestCreatePrompt:
    def test_creates_version_1_without_supersedes(self, client) -> None:
        response = client.post(
            "/prompts",
            headers=ADMIN_HEADERS,
            json={
                "text": "새 프롬프트",
                "intent": "Test",
                "target": "manager",
                "priority": "Medium",
                "language": "ko",
            },
        )

        assert response.status_code == 201
        body = response.get_json()
        assert body["version"] == 1
        assert body["supersedes_id"] is None
        assert body["is_active"] is True

    def test_creates_new_version_via_supersedes_id(self, client, db_session: Session) -> None:
        old = Prompt(
            text="기존 문구",
            intent="Test",
            target=Target.MANAGER,
            priority=Priority.MEDIUM,
            language=Language.KO,
            version=1,
        )
        db_session.add(old)
        db_session.flush()

        response = client.post(
            "/prompts",
            headers=ADMIN_HEADERS,
            json={
                "text": "수정된 문구",
                "intent": "Test",
                "target": "manager",
                "priority": "Medium",
                "language": "ko",
                "supersedes_id": old.id,
            },
        )

        assert response.status_code == 201
        body = response.get_json()
        assert body["version"] == 2
        assert body["supersedes_id"] == old.id

        # 이전 버전은 새 버전을 만든다고 자동 비활성화되지 않는다 — 명시적으로 호출해야 한다.
        old_response = client.get("/prompts")
        old_data = next(p for p in old_response.get_json() if p["id"] == old.id)
        assert old_data["is_active"] is True

    def test_supersedes_unknown_id_returns_400(self, client) -> None:
        response = client.post(
            "/prompts",
            headers=ADMIN_HEADERS,
            json={
                "text": "X",
                "intent": "Test",
                "target": "manager",
                "priority": "Medium",
                "language": "ko",
                "supersedes_id": 999999,
            },
        )
        assert response.status_code == 400

    def test_editing_text_in_place_is_not_possible(self, client) -> None:
        """PUT /prompts/{id}(텍스트 수정) 라우트 자체가 없다 — 프롬프트 불변 규칙(CLAUDE.md).
        존재하는 라우트는 /prompts/{id}/detail(GET)과 /prompts/{id}/deactivate(PUT)뿐이라
        경로 자체가 매칭되지 않아 404가 난다."""
        response = client.put("/prompts/1", headers=ADMIN_HEADERS, json={"text": "변경"})
        assert response.status_code == 404


class TestDeactivatePrompt:
    def test_deactivates_prompt(self, client, db_session: Session) -> None:
        prompt = Prompt(
            text="비활성화 대상",
            intent="Test",
            target=Target.MANAGER,
            priority=Priority.MEDIUM,
            language=Language.KO,
        )
        db_session.add(prompt)
        db_session.flush()

        response = client.put(f"/prompts/{prompt.id}/deactivate", headers=ADMIN_HEADERS)

        assert response.status_code == 200
        assert response.get_json()["is_active"] is False

    def test_deactivate_unknown_prompt_404(self, client) -> None:
        response = client.put("/prompts/999999/deactivate", headers=ADMIN_HEADERS)
        assert response.status_code == 404


class TestDeactivateAllActive:
    def test_deactivates_every_active_prompt(self, client, db_session: Session) -> None:
        active_a = Prompt(
            text="활성 A",
            intent="Test",
            target=Target.MANAGER,
            priority=Priority.MEDIUM,
            language=Language.KO,
            is_active=True,
        )
        active_b = Prompt(
            text="활성 B",
            intent="Test",
            target=Target.MANAGER,
            priority=Priority.MEDIUM,
            language=Language.KO,
            is_active=True,
        )
        already_inactive = Prompt(
            text="이미 비활성",
            intent="Test",
            target=Target.MANAGER,
            priority=Priority.MEDIUM,
            language=Language.KO,
            is_active=False,
        )
        db_session.add_all([active_a, active_b, already_inactive])
        db_session.flush()

        response = client.post("/prompts/deactivate-all", headers=ADMIN_HEADERS)

        assert response.status_code == 200
        assert response.get_json()["deactivated_count"] == 2
        db_session.refresh(active_a)
        db_session.refresh(active_b)
        assert active_a.is_active is False
        assert active_b.is_active is False

    def test_requires_admin_key(self, client) -> None:
        response = client.post("/prompts/deactivate-all")
        assert response.status_code == 401


class TestImportExcelEndpoint:
    def test_requires_admin_key(self, client) -> None:
        response = client.post("/prompts/import-excel")
        assert response.status_code == 401

    def test_missing_file_returns_400(self, client) -> None:
        response = client.post("/prompts/import-excel", headers=ADMIN_HEADERS)
        assert response.status_code == 400

    def test_valid_file_creates_prompts(self, client) -> None:
        import io

        import openpyxl

        wb = openpyxl.Workbook()
        ws = wb.active
        ws.append(
            [
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
        )
        ws.append(
            [
                "KR",
                "K-Beauty·화장품",
                "구분없음",
                "구분없음",
                "실무자",
                "정보탐색",
                "비브랜드 롱테일",
                "화장품 리드타임 단축",
                "화장품 리드타임 단축은 어떻게 하나요?",
            ]
        )
        buffer = io.BytesIO()
        wb.save(buffer)
        buffer.seek(0)

        response = client.post(
            "/prompts/import-excel",
            headers=ADMIN_HEADERS,
            data={"file": (buffer, "upload.xlsx")},
            content_type="multipart/form-data",
        )

        assert response.status_code == 201
        body = response.get_json()
        assert body["rows_processed"] == 1
        assert body["prompts_created"] == 2

    def test_invalid_row_returns_400_with_row_errors(self, client) -> None:
        import io

        import openpyxl

        wb = openpyxl.Workbook()
        ws = wb.active
        ws.append(
            [
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
        )
        ws.append(
            [
                "KR",
                "-",
                "구분없음",
                "구분없음",
                "알수없음",
                "정보탐색",
                "비브랜드 롱테일",
                "V1",
                "V2?",
            ]
        )
        buffer = io.BytesIO()
        wb.save(buffer)
        buffer.seek(0)

        response = client.post(
            "/prompts/import-excel",
            headers=ADMIN_HEADERS,
            data={"file": (buffer, "bad.xlsx")},
            content_type="multipart/form-data",
        )

        assert response.status_code == 400
        assert response.get_json()["row_errors"]
