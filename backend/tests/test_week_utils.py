from __future__ import annotations

import pytest

from app.services.week_utils import (
    compute_current_week_label,
    previous_week_label,
    recent_week_labels,
)


class TestPreviousWeekLabel:
    def test_normal_case(self) -> None:
        assert previous_week_label("2026-W28") == "2026-W27"

    def test_year_boundary_wraps_correctly(self) -> None:
        assert previous_week_label("2026-W01") == "2025-W52"


class TestRecentWeekLabels:
    def test_returns_ascending_labels_ending_at_given_week(self) -> None:
        assert recent_week_labels("2026-W28", 4) == [
            "2026-W25",
            "2026-W26",
            "2026-W27",
            "2026-W28",
        ]

    def test_single_week(self) -> None:
        assert recent_week_labels("2026-W28", 1) == ["2026-W28"]

    def test_spans_year_boundary(self) -> None:
        assert recent_week_labels("2026-W02", 4) == [
            "2025-W51",
            "2025-W52",
            "2026-W01",
            "2026-W02",
        ]

    def test_rejects_non_positive_count(self) -> None:
        with pytest.raises(ValueError, match="count는 1 이상"):
            recent_week_labels("2026-W28", 0)


class TestComputeCurrentWeekLabel:
    def test_matches_expected_format(self) -> None:
        label = compute_current_week_label()
        year, week = label.split("-W")
        assert len(year) == 4
        assert 1 <= int(week) <= 53
