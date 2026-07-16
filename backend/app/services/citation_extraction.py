"""인용(citation) 추출과 브랜드 도메인 매칭 — 순수 함수, DB/IO 없음.

우선순위: 어댑터가 반환한 citations(LLMResponse.citations)를 그대로 쓰고, 비어 있을 때만 응답
본문에서 정규식으로 URL을 추출한다.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from urllib.parse import urlsplit

_URL_RE = re.compile(r"https?://[^\s<>\)\]\"'|]+")
_TRAILING_PUNCTUATION = ".,;:!?)]}\"'"


@dataclass(frozen=True)
class BrandDomainForMatching:
    brand_id: int
    domain: str


def extract_urls_from_text(text: str) -> list[str]:
    """본문에서 URL을 정규식으로 추출한다 (어댑터 citations가 비어 있을 때의 폴백).

    문장 끝에 붙는 마침표/괄호 등은 URL의 일부가 아니므로 제거한다
    (예: "...참고하세요 (https://a.com/b)." → "https://a.com/b").
    """
    urls: list[str] = []
    seen: set[str] = set()
    for raw in _URL_RE.findall(text):
        url = raw.rstrip(_TRAILING_PUNCTUATION)
        if url and url not in seen:
            seen.add(url)
            urls.append(url)
    return urls


def parse_domain(url: str) -> str:
    """URL에서 포트를 제외한 호스트명(소문자)만 뽑아낸다. 실패하면 빈 문자열."""
    netloc = urlsplit(url).netloc
    host = netloc.split("@")[-1].split(":")[0]  # userinfo, port 제거
    return host.lower()


def match_domain_to_brand(domain: str, brand_domains: list[BrandDomainForMatching]) -> int | None:
    """서브도메인 포함 매칭: citation 도메인이 등록 도메인과 같거나, 그 서브도메인이면 매칭한다.

    예: 등록 도메인 "samsungsds.com" → "samsungsds.com", "www.samsungsds.com",
    "blog.samsungsds.com" 모두 매칭. "notsamsungsds.com"이나 "samsungsds.com.evil.net"은
    매칭하지 않는다 — endswith 검사에 앞에 점(".")을 강제해 문자열 단순 포함이 아니라 도메인
    레이블 경계를 지키게 한다.
    """
    domain = domain.lower()
    for bd in brand_domains:
        registered = bd.domain.lower()
        if domain == registered or domain.endswith("." + registered):
            return bd.brand_id
    return None


def resolve_citations(*, adapter_citations: list[str], response_text: str) -> list[str]:
    """어댑터 citations 우선, 없으면 본문 정규식 추출로 폴백."""
    if adapter_citations:
        return list(adapter_citations)
    return extract_urls_from_text(response_text)
