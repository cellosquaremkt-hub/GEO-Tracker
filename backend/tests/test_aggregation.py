from __future__ import annotations

from decimal import Decimal

from app.models.enums import Sentiment
from app.services.aggregation import calculate_snapshot_metrics


class TestSov:
    def test_normal_share(self) -> None:
        metrics = calculate_snapshot_metrics(
            mention_count=4,
            total_mentions=10,
            mention_order_sum=12,
            sentiment_counts={},
            brand_citations=0,
            total_citations=0,
        )
        assert metrics.sov == Decimal("40.000")

    def test_zero_when_nothing_mentioned_in_scope(self) -> None:
        """docs/metrics.md §1: total_mentions=0이면 0으로 나누기 대신 관례상 0으로 정의한다
        (NOT NULL)."""
        metrics = calculate_snapshot_metrics(
            mention_count=0,
            total_mentions=0,
            mention_order_sum=0,
            sentiment_counts={},
            brand_citations=0,
            total_citations=0,
        )
        assert metrics.sov == Decimal("0.000")

    def test_zero_for_unmentioned_brand_when_others_mentioned(self) -> None:
        metrics = calculate_snapshot_metrics(
            mention_count=0,
            total_mentions=10,
            mention_order_sum=0,
            sentiment_counts={},
            brand_citations=0,
            total_citations=0,
        )
        assert metrics.sov == Decimal("0.000")


class TestAvgRank:
    def test_computes_mean_mention_order(self) -> None:
        metrics = calculate_snapshot_metrics(
            mention_count=4,
            total_mentions=10,
            mention_order_sum=12,
            sentiment_counts={},
            brand_citations=0,
            total_citations=0,
        )
        assert metrics.avg_rank == Decimal("3.000")

    def test_none_when_brand_never_mentioned(self) -> None:
        """docs/metrics.md §2: 미언급 브랜드는 null — 0이나 큰 값으로 대체하지 않는다."""
        metrics = calculate_snapshot_metrics(
            mention_count=0,
            total_mentions=10,
            mention_order_sum=0,
            sentiment_counts={},
            brand_citations=0,
            total_citations=0,
        )
        assert metrics.avg_rank is None


class TestSentimentPct:
    def test_percentages_sum_to_100(self) -> None:
        metrics = calculate_snapshot_metrics(
            mention_count=4,
            total_mentions=10,
            mention_order_sum=12,
            sentiment_counts={Sentiment.POSITIVE: 2, Sentiment.NEUTRAL: 1, Sentiment.NEGATIVE: 1},
            brand_citations=0,
            total_citations=0,
        )
        assert metrics.sentiment_positive_pct == Decimal("50.000")
        assert metrics.sentiment_neutral_pct == Decimal("25.000")
        assert metrics.sentiment_negative_pct == Decimal("25.000")

    def test_none_when_brand_never_mentioned(self) -> None:
        """docs/metrics.md §3: mention_count=0이면 세 값 모두 null — 0/0/0으로 채우지 않는다."""
        metrics = calculate_snapshot_metrics(
            mention_count=0,
            total_mentions=10,
            mention_order_sum=0,
            sentiment_counts={},
            brand_citations=0,
            total_citations=0,
        )
        assert metrics.sentiment_positive_pct is None
        assert metrics.sentiment_neutral_pct is None
        assert metrics.sentiment_negative_pct is None


class TestCitationSharePct:
    def test_normal_share(self) -> None:
        metrics = calculate_snapshot_metrics(
            mention_count=0,
            total_mentions=0,
            mention_order_sum=0,
            sentiment_counts={},
            brand_citations=3,
            total_citations=5,
        )
        assert metrics.citation_share_pct == Decimal("60.000")

    def test_zero_when_brand_has_no_citations_but_others_do(self) -> None:
        metrics = calculate_snapshot_metrics(
            mention_count=0,
            total_mentions=0,
            mention_order_sum=0,
            sentiment_counts={},
            brand_citations=0,
            total_citations=5,
        )
        assert metrics.citation_share_pct == Decimal("0.000")

    def test_none_when_no_citations_in_scope_at_all(self) -> None:
        """docs/metrics.md §4: total_citations=0이면 null — 0%가 아니라 정의되지 않음."""
        metrics = calculate_snapshot_metrics(
            mention_count=0,
            total_mentions=0,
            mention_order_sum=0,
            sentiment_counts={},
            brand_citations=0,
            total_citations=0,
        )
        assert metrics.citation_share_pct is None
