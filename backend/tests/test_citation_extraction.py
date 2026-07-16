from __future__ import annotations

from app.services.citation_extraction import (
    BrandDomainForMatching,
    extract_urls_from_text,
    match_domain_to_brand,
    parse_domain,
    resolve_citations,
)


class TestExtractUrlsFromText:
    def test_strips_trailing_punctuation(self) -> None:
        text = "참고하세요: https://www.samsungsds.com/kr/logistics.html."
        assert extract_urls_from_text(text) == ["https://www.samsungsds.com/kr/logistics.html"]

    def test_strips_wrapping_parentheses(self) -> None:
        text = "자세한 내용은 (https://example.com/page)를 확인하세요."
        assert extract_urls_from_text(text) == ["https://example.com/page"]

    def test_dedupes_preserving_first_occurrence_order(self) -> None:
        text = "https://a.com/x 그리고 https://b.com/y 그리고 다시 https://a.com/x"
        assert extract_urls_from_text(text) == ["https://a.com/x", "https://b.com/y"]

    def test_no_urls_returns_empty_list(self) -> None:
        assert extract_urls_from_text("URL이 전혀 없는 문장입니다.") == []


class TestResolveCitations:
    def test_prefers_adapter_citations_when_present(self) -> None:
        result = resolve_citations(
            adapter_citations=["https://adapter.example.com/a"],
            response_text="본문에는 https://textonly.example.com/b 가 있다",
        )
        assert result == ["https://adapter.example.com/a"]

    def test_falls_back_to_text_regex_when_adapter_citations_empty(self) -> None:
        result = resolve_citations(
            adapter_citations=[],
            response_text="본문에는 https://textonly.example.com/b 가 있다",
        )
        assert result == ["https://textonly.example.com/b"]


class TestParseDomain:
    def test_lowercases_and_strips_port(self) -> None:
        assert parse_domain("https://WWW.Example.com:8443/path") == "www.example.com"

    def test_strips_userinfo(self) -> None:
        assert parse_domain("https://user:pass@example.com/path") == "example.com"


class TestMatchDomainToBrand:
    def _registry(self) -> list[BrandDomainForMatching]:
        return [
            BrandDomainForMatching(brand_id=1, domain="samsungsds.com"),
            BrandDomainForMatching(brand_id=2, domain="cellosquare.com"),
        ]

    def test_exact_domain_matches(self) -> None:
        assert match_domain_to_brand("samsungsds.com", self._registry()) == 1

    def test_subdomain_matches(self) -> None:
        assert match_domain_to_brand("www.samsungsds.com", self._registry()) == 1
        assert match_domain_to_brand("blog.samsungsds.com", self._registry()) == 1

    def test_is_case_insensitive(self) -> None:
        assert match_domain_to_brand("WWW.SamsungSDS.com", self._registry()) == 1

    def test_lookalike_prefix_domain_does_not_match(self) -> None:
        assert match_domain_to_brand("notsamsungsds.com", self._registry()) is None

    def test_lookalike_suffix_domain_does_not_match(self) -> None:
        assert match_domain_to_brand("samsungsds.com.evil.net", self._registry()) is None

    def test_unregistered_domain_returns_none(self) -> None:
        assert match_domain_to_brand("news.example.com", self._registry()) is None
