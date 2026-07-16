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
