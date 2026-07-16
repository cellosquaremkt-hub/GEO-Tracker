from __future__ import annotations

from app.models.enums import Sentiment
from app.services.response_parser import BrandInfo, ExecutionRunInput, parse_response
from app.services.sentiment import (
    KeywordRuleSentimentClassifier,
    SentimentClassifier,
    SentimentResult,
)


class _FixedSentimentClassifier(SentimentClassifier):
    """모든 언급을 고정된 감정으로 판정하는 가짜 분류기 — 오케스트레이션 로직만 검증할 때 사용."""

    def __init__(self, sentiment: Sentiment = Sentiment.NEUTRAL) -> None:
        self._sentiment = sentiment

    def classify(self, *, brand_name: str, context: str) -> SentimentResult:
        return SentimentResult(sentiment=self._sentiment, evidence=f"[{brand_name}] {context[:20]}")


def _brands() -> list[BrandInfo]:
    return [
        BrandInfo(id=1, name="삼성SDS", aliases=("Samsung SDS",), domains=("samsungsds.com",)),
        BrandInfo(id=2, name="첼로스퀘어", aliases=("Cello Square",), domains=("cellosquare.com",)),
        BrandInfo(
            id=3,
            name="Kuehne+Nagel",
            aliases=("K+N", "퀴네나겔"),
            domains=("kuehne-nagel.com",),
        ),
    ]


class TestParseResponseMentions:
    def test_assigns_mention_order_by_first_occurrence(self) -> None:
        text = "K+N과 비교하면 삼성SDS의 첼로스퀘어가 더 앞서 있습니다."
        run = ExecutionRunInput(raw_response=text)
        result = parse_response(run, _brands(), sentiment_classifier=_FixedSentimentClassifier())

        assert [m.brand_id for m in result.mentions] == [3, 1, 2]
        assert [m.mention_order for m in result.mentions] == [1, 2, 3]

    def test_unmentioned_brand_has_no_mention_row(self) -> None:
        text = "삼성SDS만 언급되는 문장입니다."
        run = ExecutionRunInput(raw_response=text)
        result = parse_response(run, _brands(), sentiment_classifier=_FixedSentimentClassifier())

        assert [m.brand_id for m in result.mentions] == [1]

    def test_sentiment_and_evidence_come_from_classifier(self) -> None:
        text = "삼성SDS는 훌륭합니다."
        run = ExecutionRunInput(raw_response=text)
        classifier = _FixedSentimentClassifier(sentiment=Sentiment.POSITIVE)
        result = parse_response(run, _brands(), sentiment_classifier=classifier)

        assert result.mentions[0].sentiment == Sentiment.POSITIVE
        assert "삼성SDS" in (result.mentions[0].sentiment_evidence or "")

    def test_realistic_text_with_keyword_classifier(self) -> None:
        """긍정/부정 문장 사이에 중립 문장을 하나 두어, ±1문장 윈도우가 서로의 감정 키워드를
        섞어버리지 않게 한 현실적인 케이스 (윈도우 오염은 test_sentiment.py에서 별도로 다룬다)."""
        text = (
            "삼성SDS의 첼로스퀘어는 업계에서 신뢰받는 선도 서비스로 꼽힙니다. "
            "국내 물류 시장은 계속 성장하고 있습니다. "
            "반면 퀴네나겔은 최근 배송 지연으로 불만이 제기되었습니다."
        )
        run = ExecutionRunInput(raw_response=text)
        result = parse_response(
            run, _brands(), sentiment_classifier=KeywordRuleSentimentClassifier()
        )

        by_brand = {m.brand_id: m for m in result.mentions}
        assert by_brand[1].sentiment == Sentiment.POSITIVE
        assert by_brand[2].sentiment == Sentiment.POSITIVE
        assert by_brand[3].sentiment == Sentiment.NEGATIVE


class TestParseResponseCitations:
    def test_uses_adapter_citations_when_present(self) -> None:
        text = "본문에는 https://textonly.example.com/ignored 가 있다."
        run = ExecutionRunInput(
            raw_response=text, adapter_citations=("https://www.samsungsds.com/kr/page",)
        )
        result = parse_response(run, _brands(), sentiment_classifier=_FixedSentimentClassifier())

        assert [c.url for c in result.citations] == ["https://www.samsungsds.com/kr/page"]
        assert result.citations[0].matched_brand_id == 1

    def test_falls_back_to_text_regex_when_no_adapter_citations(self) -> None:
        text = "참고: https://blog.cellosquare.com/post 그리고 https://news.example.com/x"
        run = ExecutionRunInput(raw_response=text)
        result = parse_response(run, _brands(), sentiment_classifier=_FixedSentimentClassifier())

        urls = [c.url for c in result.citations]
        assert urls == ["https://blog.cellosquare.com/post", "https://news.example.com/x"]
        matched = {c.url: c.matched_brand_id for c in result.citations}
        assert matched["https://blog.cellosquare.com/post"] == 2
        assert matched["https://news.example.com/x"] is None
