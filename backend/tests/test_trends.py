from __future__ import annotations

from decimal import Decimal

from sqlalchemy.orm import Session

from app.models.brand import Brand
from app.models.snapshot import WeeklySnapshot


class TestTrends:
    def test_returns_series_per_brand_with_nulls_for_missing_weeks(
        self, client, db_session: Session
    ) -> None:
        brand_a = Brand(name="삼성SDS", is_own=True)
        brand_b = Brand(name="LX Pantos", is_own=False)
        db_session.add_all([brand_a, brand_b])
        db_session.flush()

        # brand_a는 2주 모두 데이터가 있고, brand_b는 최신 주만 있다.
        db_session.add_all(
            [
                WeeklySnapshot(
                    week_label="2026-W27",
                    brand_id=brand_a.id,
                    llm_provider_id=None,
                    sov=Decimal("20.000"),
                    total_runs=5,
                ),
                WeeklySnapshot(
                    week_label="2026-W28",
                    brand_id=brand_a.id,
                    llm_provider_id=None,
                    sov=Decimal("25.000"),
                    total_runs=5,
                ),
                WeeklySnapshot(
                    week_label="2026-W28",
                    brand_id=brand_b.id,
                    llm_provider_id=None,
                    sov=Decimal("40.000"),
                    total_runs=5,
                ),
            ]
        )
        db_session.flush()

        response = client.get("/trends?weeks=2&week=2026-W28")

        assert response.status_code == 200
        body = response.get_json()
        assert body["weeks"] == ["2026-W27", "2026-W28"]
        series_by_brand = {s["brand_id"]: s for s in body["series"]}

        a_points = {p["week"]: p["sov"] for p in series_by_brand[brand_a.id]["points"]}
        assert a_points == {"2026-W27": "20.000", "2026-W28": "25.000"}

        b_points = {p["week"]: p["sov"] for p in series_by_brand[brand_b.id]["points"]}
        assert b_points == {"2026-W27": None, "2026-W28": "40.000"}

    def test_works_with_zero_brands(self, client) -> None:
        response = client.get("/trends?weeks=4")
        assert response.status_code == 200
        body = response.get_json()
        assert body["series"] == []
        assert len(body["weeks"]) == 4

    def test_weeks_query_param_bounds(self, client) -> None:
        assert client.get("/trends?weeks=0").status_code == 422
        assert client.get("/trends?weeks=53").status_code == 422
