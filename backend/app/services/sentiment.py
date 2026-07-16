"""브랜드 언급의 감정(sentiment) 분류.

SentimentClassifier 인터페이스를 분리해 구현체를 교체 가능하게 한다. 현재 유일한 구현체는
KeywordRuleSentimentClassifier(순수 규칙 기반, IO 없음)이다 — STEP 6부터 OpenAI API 키가 없어
LLM 기반 분류기는 이식하지 않았다(참고 프로젝트 app/services/sentiment.py의
LLMSentimentClassifier, docs/backlog.md 참조 — API 키를 다시 받으면 그때 이식한다).

get_default_sentiment_classifier()는 항상 KeywordRuleSentimentClassifier를 반환한다.
"""

from __future__ import annotations

import abc
import re
from dataclasses import dataclass

from app.models.enums import Sentiment

# 키워드 규칙 폴백. 대소문자 무시 부분 문자열 매칭.
POSITIVE_KEYWORDS: tuple[str, ...] = (
    "추천",
    "우수",
    "강점",
    "선도",
    "신뢰",
    "만족",
    "최고",
    "효율적",
    "돋보",
    "앞서",
    "leading",
    "recommend",
    "excellent",
    "trusted",
    "strong",
    "best",
    "reliable",
    "outperform",
    "impressive",
    "preferred",
)
NEGATIVE_KEYWORDS: tuple[str, ...] = (
    "단점",
    "느리",
    "불만",
    "지연",
    "실패",
    "취약",
    "우려",
    "저하",
    "부족",
    "불편",
    "risk",
    "delay",
    "complaint",
    "poor",
    "weak",
    "issue",
    "problem",
    "worse",
    "fail",
    "concern",
    "lacking",
)

_SENTENCE_END_RE = re.compile(r"(?<=[.!?。])\s+")


@dataclass(frozen=True)
class SentimentResult:
    sentiment: Sentiment
    evidence: str | None


class SentimentClassifier(abc.ABC):
    @abc.abstractmethod
    def classify(self, *, brand_name: str, context: str) -> SentimentResult:
        """context(± 1문장) 안에서 brand_name에 대한 감정을 판정한다."""


def _split_sentences(text: str) -> list[tuple[int, int]]:
    """(start, end) 오프셋 목록. 문장 끝 표시(.!?。) 뒤 공백/개행을 경계로 본다."""
    spans: list[tuple[int, int]] = []
    start = 0
    for m in _SENTENCE_END_RE.finditer(text):
        spans.append((start, m.start()))
        start = m.end()
    spans.append((start, len(text)))
    return [s for s in spans if s[1] > s[0]]


def extract_context_sentences(text: str, match_start: int, match_end: int) -> str:
    """언급 위치를 포함한 문장 ± 앞뒤 1문장을 이어붙여 반환한다."""
    spans = _split_sentences(text)
    if not spans:
        return text.strip()

    idx = len(spans) - 1
    for i, (s, e) in enumerate(spans):
        if s <= match_start < e:
            idx = i
            break

    lo = max(0, idx - 1)
    hi = min(len(spans), idx + 2)
    parts = [text[s:e].strip() for s, e in spans[lo:hi]]
    return " ".join(p for p in parts if p)


def _evidence_snippet(context: str, keyword: str, *, window: int = 20) -> str:
    idx = context.lower().find(keyword.lower())
    if idx == -1:
        return context[:80]
    start = max(0, idx - window)
    end = min(len(context), idx + len(keyword) + window)
    return context[start:end].strip()


class KeywordRuleSentimentClassifier(SentimentClassifier):
    """규칙 기반 폴백. 긍/부정 키워드가 둘 다(또는 둘 다 아님) 나오면 중립으로 판정한다."""

    def classify(self, *, brand_name: str, context: str) -> SentimentResult:
        lowered = context.lower()
        positive_hits = [kw for kw in POSITIVE_KEYWORDS if kw.lower() in lowered]
        negative_hits = [kw for kw in NEGATIVE_KEYWORDS if kw.lower() in lowered]

        if positive_hits and not negative_hits:
            return SentimentResult(Sentiment.POSITIVE, _evidence_snippet(context, positive_hits[0]))
        if negative_hits and not positive_hits:
            return SentimentResult(Sentiment.NEGATIVE, _evidence_snippet(context, negative_hits[0]))
        return SentimentResult(Sentiment.NEUTRAL, evidence=None)


def get_default_sentiment_classifier() -> SentimentClassifier:
    """항상 KeywordRuleSentimentClassifier를 반환한다 — 이 함수를 통해서만 분류기를 얻을 것.

    STEP 6부터 회사 사정으로 OpenAI API 키 자체가 없어(docs/backlog.md), LLM 기반 분류기는
    이식하지 않았다(migration_flask_postgres.md §3.1 Phase 2 범위 참조). 나중에 API 키를 받으면
    LLMSentimentClassifier를 참고 프로젝트에서 이식하고 이 함수의 분기를 되살리면 된다.
    """
    return KeywordRuleSentimentClassifier()
