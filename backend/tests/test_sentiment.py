from __future__ import annotations

from app.models.enums import Sentiment
from app.services.sentiment import (
    KeywordRuleSentimentClassifier,
    extract_context_sentences,
    get_default_sentiment_classifier,
)


class TestExtractContextSentences:
    def test_includes_previous_and_next_sentence(self) -> None:
        text = "첫 문장입니다. 둘째 문장에 브랜드가 나옵니다. 셋째 문장입니다."
        idx = text.find("브랜드")
        context = extract_context_sentences(text, idx, idx + 3)
        assert "첫 문장입니다." in context
        assert "둘째 문장에 브랜드가 나옵니다." in context
        assert "셋째 문장입니다." in context

    def test_first_sentence_has_no_previous(self) -> None:
        text = "브랜드가 나오는 첫 문장입니다. 둘째 문장입니다."
        idx = text.find("브랜드")
        context = extract_context_sentences(text, idx, idx + 3)
        assert context.startswith("브랜드가 나오는 첫 문장입니다.")
        assert "둘째 문장입니다." in context

    def test_last_sentence_has_no_next(self) -> None:
        text = "첫 문장입니다. 브랜드가 나오는 마지막 문장입니다."
        idx = text.find("브랜드")
        context = extract_context_sentences(text, idx, idx + 3)
        assert context.endswith("브랜드가 나오는 마지막 문장입니다.")

    def test_single_sentence_text(self) -> None:
        text = "브랜드만 있는 문장"
        context = extract_context_sentences(text, 0, 3)
        assert context == "브랜드만 있는 문장"


class TestKeywordRuleSentimentClassifier:
    def _classifier(self) -> KeywordRuleSentimentClassifier:
        return KeywordRuleSentimentClassifier()

    def test_positive_keyword_yields_positive(self) -> None:
        result = self._classifier().classify(
            brand_name="첼로스퀘어", context="첼로스퀘어는 업계에서 신뢰받는 선도 서비스입니다."
        )
        assert result.sentiment == Sentiment.POSITIVE
        assert result.evidence

    def test_negative_keyword_yields_negative(self) -> None:
        result = self._classifier().classify(
            brand_name="경쟁사", context="경쟁사는 최근 지연 문제로 불만이 제기되었습니다."
        )
        assert result.sentiment == Sentiment.NEGATIVE
        assert result.evidence

    def test_no_keywords_yields_neutral(self) -> None:
        result = self._classifier().classify(
            brand_name="브랜드", context="브랜드는 물류 서비스를 제공합니다."
        )
        assert result.sentiment == Sentiment.NEUTRAL
        assert result.evidence is None

    def test_mixed_signals_yield_neutral(self) -> None:
        """긍정·부정 키워드가 함께 나오면(예: ±1문장 윈도우가 이웃 문장을 끌어온 경우) 중립으로
        판정한다 — 의도된 트레이드오프이며, response_parser의 문맥 윈도우 크기 때문에 실제로
        발생할 수 있는 상황이다."""
        result = self._classifier().classify(
            brand_name="브랜드",
            context="브랜드는 신뢰받는 선도 기업입니다. 하지만 최근 지연 문제로 불만도 있습니다.",
        )
        assert result.sentiment == Sentiment.NEUTRAL

    def test_english_keywords_are_case_insensitive(self) -> None:
        result = self._classifier().classify(
            brand_name="Brand", context="Brand is widely considered a TRUSTED and RELIABLE choice."
        )
        assert result.sentiment == Sentiment.POSITIVE


class TestDefaultClassifierFactory:
    def test_returns_keyword_rule_classifier(self) -> None:
        """STEP 6부터 OpenAI API 키가 없어 LLM 기반 분류기는 이식하지 않았다 —
        get_default_sentiment_classifier()는 항상 KeywordRuleSentimentClassifier를 반환한다
        (app/services/sentiment.py 참조)."""
        assert isinstance(get_default_sentiment_classifier(), KeywordRuleSentimentClassifier)
