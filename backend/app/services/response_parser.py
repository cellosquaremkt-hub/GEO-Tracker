"""LLM 응답에서 브랜드 언급/감정/인용을 뽑아내는 파싱 엔진 (오케스트레이션 계층).

DB 접근과 순수 파싱 로직을 분리한다 — 이 모듈은 SQLAlchemy를 import하지 않는다. 호출자가
Brand/BrandAlias/BrandDomain/ExecutionRun을 조회해 아래 데이터클래스로 변환해 넘기고, 반환된
ParsedResponse를 Mention/Citation ORM으로 바꿔 저장하는 것은 호출자(배치 워커 등 상위 계층)의
책임이다. brand_matching.py/citation_extraction.py의 실제 매칭 로직은 완전한 순수 함수이고,
이 모듈은 그 순수 함수들과 (부수효과가 있는) SentimentClassifier를 조합하기만 한다.
"""

from __future__ import annotations

from dataclasses import dataclass

from app.models.enums import Sentiment
from app.services.brand_matching import (
    BrandForMatching,
    find_all_alias_matches,
    first_mention_per_brand,
)
from app.services.citation_extraction import (
    BrandDomainForMatching,
    match_domain_to_brand,
    parse_domain,
    resolve_citations,
)
from app.services.sentiment import SentimentClassifier, extract_context_sentences


@dataclass(frozen=True)
class BrandInfo:
    """매칭에 필요한 브랜드 정보 — Brand + BrandAlias + BrandDomain을 합친 순수 데이터."""

    id: int
    name: str
    aliases: tuple[str, ...] = ()
    domains: tuple[str, ...] = ()

    def as_matching(self) -> BrandForMatching:
        return BrandForMatching(id=self.id, name=self.name, aliases=self.aliases)

    def domain_entries(self) -> list[BrandDomainForMatching]:
        return [BrandDomainForMatching(brand_id=self.id, domain=d) for d in self.domains]


@dataclass(frozen=True)
class ExecutionRunInput:
    """parse_response에 필요한 execution_run 필드만 뽑은 순수 데이터.

    adapter_citations는 LLMResponse.citations(배치 실행 시 어댑터가 반환한 값)를 그대로
    전달한다 — 비어 있을 때만 raw_response에서 정규식으로 URL을 추출하는 폴백이 동작한다.
    """

    raw_response: str
    adapter_citations: tuple[str, ...] = ()


@dataclass(frozen=True)
class MentionResult:
    brand_id: int
    mention_order: int
    sentiment: Sentiment
    sentiment_evidence: str | None


@dataclass(frozen=True)
class CitationResult:
    url: str
    domain: str
    matched_brand_id: int | None


@dataclass(frozen=True)
class ParsedResponse:
    mentions: list[MentionResult]
    citations: list[CitationResult]


def parse_response(
    execution_run: ExecutionRunInput,
    brands: list[BrandInfo],
    *,
    sentiment_classifier: SentimentClassifier,
) -> ParsedResponse:
    text = execution_run.raw_response

    matching_brands = [b.as_matching() for b in brands]
    all_matches = find_all_alias_matches(text, matching_brands)
    firsts = first_mention_per_brand(all_matches)

    brand_names_by_id = {b.id: b.name for b in brands}
    mentions: list[MentionResult] = []
    for order, match in enumerate(firsts, start=1):
        context = extract_context_sentences(text, match.start, match.end)
        result = sentiment_classifier.classify(
            brand_name=brand_names_by_id[match.brand_id], context=context
        )
        mentions.append(
            MentionResult(
                brand_id=match.brand_id,
                mention_order=order,
                sentiment=result.sentiment,
                sentiment_evidence=result.evidence,
            )
        )

    domain_entries = [entry for b in brands for entry in b.domain_entries()]
    urls = resolve_citations(
        adapter_citations=list(execution_run.adapter_citations), response_text=text
    )
    citations: list[CitationResult] = []
    for url in urls:
        domain = parse_domain(url)
        matched_brand_id = match_domain_to_brand(domain, domain_entries)
        citations.append(CitationResult(url=url, domain=domain, matched_brand_id=matched_brand_id))

    return ParsedResponse(mentions=mentions, citations=citations)
