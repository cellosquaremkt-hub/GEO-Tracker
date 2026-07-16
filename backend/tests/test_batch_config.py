from __future__ import annotations

from sqlalchemy.orm import Session

from app.core.config import settings
from app.models.batch_config import BatchConfig
from app.services.batch_config_service import get_repeat_count, update_repeat_count

ADMIN_HEADERS = {"X-Admin-Api-Key": settings.admin_api_key}


class TestGetRepeatCountService:
    def test_falls_back_to_settings_when_no_row(self, db_session: Session) -> None:
        result = get_repeat_count(db_session)
        assert result == settings.repeat_count

    def test_returns_db_value_when_row_exists(self, db_session: Session) -> None:
        db_session.add(BatchConfig(id=1, repeat_count=7))
        db_session.flush()
        result = get_repeat_count(db_session)
        assert result == 7


class TestUpdateRepeatCountService:
    def test_creates_row_when_missing(self, db_session: Session) -> None:
        result = update_repeat_count(db_session, 5)
        assert result == 5
        assert get_repeat_count(db_session) == 5

    def test_updates_existing_row(self, db_session: Session) -> None:
        db_session.add(BatchConfig(id=1, repeat_count=3))
        db_session.flush()
        result = update_repeat_count(db_session, 9)
        assert result == 9
        assert get_repeat_count(db_session) == 9


class TestAuth:
    def test_get_requires_admin_key(self, client) -> None:
        assert client.get("/batch-config").status_code == 401

    def test_put_requires_admin_key(self, client) -> None:
        response = client.put("/batch-config", json={"repeat_count": 5})
        assert response.status_code == 401


class TestBatchConfigEndpoint:
    def test_get_returns_settings_default_when_no_row(self, client) -> None:
        response = client.get("/batch-config", headers=ADMIN_HEADERS)
        assert response.status_code == 200
        assert response.get_json()["repeat_count"] == settings.repeat_count

    def test_put_then_get_roundtrip(self, client) -> None:
        put_response = client.put("/batch-config", headers=ADMIN_HEADERS, json={"repeat_count": 6})
        assert put_response.status_code == 200
        assert put_response.get_json()["repeat_count"] == 6

        get_response = client.get("/batch-config", headers=ADMIN_HEADERS)
        assert get_response.get_json()["repeat_count"] == 6

    def test_rejects_out_of_range_value(self, client) -> None:
        response = client.put("/batch-config", headers=ADMIN_HEADERS, json={"repeat_count": 0})
        assert response.status_code == 422

        response = client.put("/batch-config", headers=ADMIN_HEADERS, json={"repeat_count": 21})
        assert response.status_code == 422
