from __future__ import annotations

from app.services.brand_matching import (
    BrandForMatching,
    find_all_alias_matches,
    first_mention_per_brand,
)


def _match_texts(text: str, brands: list[BrandForMatching]) -> list[str]:
    return [m.matched_text for m in find_all_alias_matches(text, brands)]


class TestKoreanParticleAttachment:
    """한국어는 조사가 명사에 공백 없이 붙는다 — 브랜드 뒤에 조사가 와도 매칭되어야 한다."""

    def test_matches_brand_name_with_trailing_particle(self) -> None:
        brand = BrandForMatching(id=1, name="삼성SDS")
        assert _match_texts("삼성SDS는 물류 플랫폼입니다.", [brand]) == ["삼성SDS"]
        assert _match_texts("삼성SDS와 협력합니다.", [brand]) == ["삼성SDS"]
        assert _match_texts("삼성SDS를 도입했습니다.", [brand]) == ["삼성SDS"]

    def test_matches_korean_alias_with_trailing_particle(self) -> None:
        brand = BrandForMatching(id=1, name="Cello Square", aliases=("첼로스퀘어",))
        assert _match_texts("첼로스퀘어는 국내 1위 서비스입니다.", [brand]) == ["첼로스퀘어"]

    def test_matches_with_korean_prefix_attached(self) -> None:
        brand = BrandForMatching(id=1, name="DHL")
        assert _match_texts("오DHL사와는 무관합니다.", [brand]) == ["DHL"]


class TestFlexibleSeparatorVariants:
    """ "K+N" / "K N" / "K-N" / "KN"처럼 구두점·공백 변형을 동일 별칭으로 인식해야 한다."""

    def test_plus_space_and_hyphen_variants_all_match(self) -> None:
        brand = BrandForMatching(id=1, name="Kuehne+Nagel", aliases=("K+N",))
        for variant in ["K+N", "K N", "K-N", "K.N"]:
            text = f"경쟁사 {variant}은 최근 성장했습니다."
            assert _match_texts(text, [brand]) == [variant], variant

    def test_full_name_separator_variants(self) -> None:
        brand = BrandForMatching(id=1, name="Kuehne+Nagel", aliases=("Kuehne nagel",))
        assert _match_texts("Kuehne+Nagel is a competitor.", [brand]) == ["Kuehne+Nagel"]
        assert _match_texts("Kuehne nagel is a competitor.", [brand]) == ["Kuehne nagel"]


class TestShortAliasFalsePositiveGuard:
    """짧은 라틴 약어(<=3자)의 오탐 방지 정책 — brand_matching.py 모듈 docstring 참조."""

    def test_short_alias_does_not_match_inside_longer_latin_token(self) -> None:
        brand = BrandForMatching(id=1, name="DHL")
        assert _match_texts("ADHLB and DHLX and XDHL are unrelated tokens.", [brand]) == []

    def test_short_alias_matches_as_standalone_word(self) -> None:
        brand = BrandForMatching(id=1, name="DHL")
        assert _match_texts("DHL is a logistics company.", [brand]) == ["DHL"]

    def test_short_alias_is_case_sensitive(self) -> None:
        """DHL처럼 짧은 약어는 실무 관행상 항상 대문자로 쓰이므로, 소문자 우연 일치는 매칭하지
        않는다 (일반 단어와의 오탐 방지 정책)."""
        brand = BrandForMatching(id=1, name="DHL")
        assert _match_texts("dhl is not necessarily the brand here.", [brand]) == []

    def test_long_alias_remains_case_insensitive(self) -> None:
        brand = BrandForMatching(id=1, name="Flexport")
        assert _match_texts("FLEXPORT and flexport both match.", [brand]) == [
            "FLEXPORT",
            "flexport",
        ]


class TestMentionOrder:
    def test_first_mention_per_brand_orders_by_first_occurrence(self) -> None:
        brands = [
            BrandForMatching(id=1, name="삼성SDS"),
            BrandForMatching(id=2, name="첼로스퀘어"),
            BrandForMatching(id=3, name="DHL"),
        ]
        text = "DHL과 비교하면 삼성SDS의 첼로스퀘어가 더 앞서 있습니다. DHL은 또 언급됩니다."
        matches = find_all_alias_matches(text, brands)
        firsts = first_mention_per_brand(matches)
        assert [m.brand_id for m in firsts] == [3, 1, 2]

    def test_unmatched_brand_produces_no_entry(self) -> None:
        brands = [
            BrandForMatching(id=1, name="삼성SDS"),
            BrandForMatching(id=2, name="언급되지않는브랜드"),
        ]
        text = "삼성SDS만 언급되는 문장입니다."
        firsts = first_mention_per_brand(find_all_alias_matches(text, brands))
        assert [m.brand_id for m in firsts] == [1]
