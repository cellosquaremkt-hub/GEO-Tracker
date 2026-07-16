from __future__ import annotations

from sqlalchemy.orm import Session

from app.core.config import settings
from app.models.brand import Brand, BrandAlias, BrandDomain

ADMIN_HEADERS = {"X-Admin-Api-Key": settings.admin_api_key}


class TestAuth:
    def test_list_brands_requires_admin_key(self, client) -> None:
        assert client.get("/brands").status_code == 401

    def test_create_brand_requires_admin_key(self, client) -> None:
        response = client.post("/brands", json={"name": "X"})
        assert response.status_code == 401


class TestListAndGetBrand:
    def test_list_includes_aliases_and_domains(self, client, db_session: Session) -> None:
        brand = Brand(name="삼성SDS", is_own=True)
        db_session.add(brand)
        db_session.flush()

        response = client.get("/brands", headers=ADMIN_HEADERS)

        assert response.status_code == 200
        body = response.get_json()
        assert len(body) == 1
        assert body[0]["name"] == "삼성SDS"
        assert body[0]["aliases"] == []
        assert body[0]["domains"] == []

    def test_get_unknown_brand_404(self, client) -> None:
        response = client.get("/brands/999999", headers=ADMIN_HEADERS)
        assert response.status_code == 404


class TestCreateBrand:
    def test_creates_brand_with_aliases_and_domains(self, client) -> None:
        response = client.post(
            "/brands",
            headers=ADMIN_HEADERS,
            json={
                "name": "Kuehne+Nagel",
                "is_own": False,
                "aliases": ["K+N", "퀴네나겔"],
                "domains": ["kuehne-nagel.com"],
            },
        )

        assert response.status_code == 201
        body = response.get_json()
        assert body["name"] == "Kuehne+Nagel"
        assert {a["alias_text"] for a in body["aliases"]} == {"K+N", "퀴네나겔"}
        assert [d["domain"] for d in body["domains"]] == ["kuehne-nagel.com"]

    def test_duplicate_name_returns_409(self, client, db_session: Session) -> None:
        db_session.add(Brand(name="DHL", is_own=False))
        db_session.flush()

        response = client.post("/brands", headers=ADMIN_HEADERS, json={"name": "DHL"})

        assert response.status_code == 409

    def test_duplicate_domain_returns_409(self, client, db_session: Session) -> None:
        existing = Brand(name="DHL", is_own=False)
        db_session.add(existing)
        db_session.flush()
        db_session.add(BrandDomain(brand_id=existing.id, domain="dhl.com"))
        db_session.flush()

        response = client.post(
            "/brands",
            headers=ADMIN_HEADERS,
            json={"name": "Fake DHL", "domains": ["dhl.com"]},
        )

        assert response.status_code == 409


class TestUpdateBrand:
    def test_updates_name_and_is_own(self, client, db_session: Session) -> None:
        brand = Brand(name="Old Name", is_own=False)
        db_session.add(brand)
        db_session.flush()

        response = client.put(
            f"/brands/{brand.id}",
            headers=ADMIN_HEADERS,
            json={"name": "New Name", "is_own": True},
        )

        assert response.status_code == 200
        body = response.get_json()
        assert body["name"] == "New Name"
        assert body["is_own"] is True

    def test_replaces_aliases_when_provided(self, client, db_session: Session) -> None:
        brand = Brand(name="LX Pantos", is_own=False)
        db_session.add(brand)
        db_session.flush()
        db_session.add(BrandAlias(brand_id=brand.id, alias_text="구별칭"))
        db_session.flush()

        response = client.put(
            f"/brands/{brand.id}", headers=ADMIN_HEADERS, json={"aliases": ["판토스"]}
        )

        assert response.status_code == 200
        body = response.get_json()
        assert [a["alias_text"] for a in body["aliases"]] == ["판토스"]

    def test_omitted_aliases_field_leaves_existing_untouched(
        self, client, db_session: Session
    ) -> None:
        brand = Brand(name="LX Pantos", is_own=False)
        db_session.add(brand)
        db_session.flush()
        db_session.add(BrandAlias(brand_id=brand.id, alias_text="판토스"))
        db_session.flush()

        response = client.put(
            f"/brands/{brand.id}", headers=ADMIN_HEADERS, json={"name": "LX Pantos Co."}
        )

        assert response.status_code == 200
        body = response.get_json()
        assert [a["alias_text"] for a in body["aliases"]] == ["판토스"]

    def test_update_unknown_brand_404(self, client) -> None:
        response = client.put("/brands/999999", headers=ADMIN_HEADERS, json={"name": "X"})
        assert response.status_code == 404
