from __future__ import annotations

from sqlalchemy.orm import Session

from app.core.config import settings
from app.models.llm_provider import LLMProvider

ADMIN_HEADERS = {"X-Admin-Api-Key": settings.admin_api_key}


class TestAuth:
    def test_list_requires_admin_key(self, client) -> None:
        assert client.get("/llm-providers").status_code == 401

    def test_update_requires_admin_key(self, client) -> None:
        response = client.put("/llm-providers/1", json={"is_active": False})
        assert response.status_code == 401


class TestListProviders:
    def test_lists_all_providers(self, client, db_session: Session) -> None:
        db_session.add(LLMProvider(name="claude-code-cli", model_string="sonnet"))
        db_session.flush()

        response = client.get("/llm-providers", headers=ADMIN_HEADERS)

        assert response.status_code == 200
        body = response.get_json()
        assert len(body) == 1
        assert body[0]["name"] == "claude-code-cli"
        assert body[0]["is_active"] is True


class TestUpdateProvider:
    def test_toggles_active_flag(self, client, db_session: Session) -> None:
        provider = LLMProvider(name="gemini-cli", model_string="gemini-2.5-pro")
        db_session.add(provider)
        db_session.flush()

        response = client.put(
            f"/llm-providers/{provider.id}", headers=ADMIN_HEADERS, json={"is_active": False}
        )

        assert response.status_code == 200
        assert response.get_json()["is_active"] is False

    def test_updates_model_string(self, client, db_session: Session) -> None:
        provider = LLMProvider(name="codex-cli", model_string="gpt-5.4")
        db_session.add(provider)
        db_session.flush()

        response = client.put(
            f"/llm-providers/{provider.id}",
            headers=ADMIN_HEADERS,
            json={"model_string": "gpt-5.5"},
        )

        assert response.status_code == 200
        assert response.get_json()["model_string"] == "gpt-5.5"

    def test_name_field_is_not_accepted(self, client, db_session: Session) -> None:
        provider = LLMProvider(name="codex-cli", model_string="gpt-5.4")
        db_session.add(provider)
        db_session.flush()

        response = client.put(
            f"/llm-providers/{provider.id}",
            headers=ADMIN_HEADERS,
            json={"name": "SomethingElse"},
        )

        # 스키마에 없는 필드는 무시되고, name은 그대로 남는다.
        assert response.status_code == 200
        assert response.get_json()["name"] == "codex-cli"

    def test_update_unknown_provider_404(self, client) -> None:
        response = client.put(
            "/llm-providers/999999", headers=ADMIN_HEADERS, json={"is_active": False}
        )
        assert response.status_code == 404
