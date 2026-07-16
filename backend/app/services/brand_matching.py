"""브랜드 언급(별칭) 매칭 — 순수 함수, DB/IO 없음.

CLAUDE.md 핵심 도메인 규칙: 브랜드는 고유 ID로만 참조한다. 이 모듈은 brand_id 기준으로만
동작하고 배열 순서 인덱스를 쓰지 않는다.

## 단어 경계(오탐 방지) 정책

일반적인 정규식 `\\b...\\b`는 이 도메인에 그대로 쓰기 어렵다 — 한국어는 조사가 명사에 공백 없이
바로 붙기 때문이다(예: "삼성SDS와", "첼로스퀘어는"). `\\b`는 라틴 문자와 한글을 모두 "단어 문자"로
취급하므로, 별칭 뒤에 조사가 붙으면 경계가 아예 생기지 않아 매칭에 실패한다.

그래서 이 모듈은 `\\b` 대신 **라틴 알파벳/숫자만 경계 문자로 취급**하는 lookaround를 쓴다:

- 매칭 앞/뒤에 라틴 문자(A-Z, a-z)나 숫자가 있으면 매칭하지 않는다 (예: "DHL"이 "DHLX"나
  "XDHL" 안에서 매칭되지 않음 — 더 긴 라틴 토큰의 일부를 잘라 매칭하는 오탐 방지).
- 매칭 앞/뒤에 한글이 있는 것은 허용한다 (조사·복합명사 대응). 이는 "삼성SDS솔루션"처럼 한글
  단어가 바로 붙는 경우도 매칭시키는 트레이드오프를 받아들인다는 뜻이다 — 완벽한 한국어 형태소
  분석 없이는 조사와 복합명사를 구분할 수 없고, 이 도메인에서는 과매칭(브랜드가 언급된 것으로
  잘못 판단)보다 미매칭(언급을 놓치는 것)의 비용이 더 크다고 보기 때문이다.

짧은 라틴 약어("DHL", "K+N" → "KN")는 일반 단어와 우연히 겹칠 위험이 있다(예: "IT", "US" 같은
2~3글자 약어). 이를 줄이기 위해 **정규화 후 길이가 SHORT_ALIAS_MAX_LEN 이하인 라틴 약어는
대소문자를 정확히 일치시켜야 매칭된다** (대소문자 무시 안 함). 브랜드 약어는 실무에서 항상
대문자로 표기되는 관행(DHL, K+N, LX 등)을 이용한 방침이다. 한글로만 된 짧은 별칭은 이 규칙의
적용 대상이 아니다(대소문자 개념이 없고, 한글 2~3음절이 일반 단어와 겹칠 확률은 라틴 약어보다
낮다고 판단).
"""

from __future__ import annotations

import re
from dataclasses import dataclass

SHORT_ALIAS_MAX_LEN = 3

# 별칭 내부의 공백/구두점/특수문자를 "구분자"로 보고 토큰화한다. 토큰 사이에는 이 구분자가
# 0개 이상 자유롭게 올 수 있다고 보고 매칭한다 — "K+N" == "K N" == "KN" == "K-N".
_TOKEN_SPLIT_RE = re.compile(r"[\s\-+&.·/]+")
_FLEXIBLE_SEPARATOR = r"[\s\-+&.·/]*"
_LATIN_ALNUM = "A-Za-z0-9"


@dataclass(frozen=True)
class BrandForMatching:
    """DB의 Brand+BrandAlias를 매칭 함수에 넘기기 위한 순수 데이터 표현."""

    id: int
    name: str
    aliases: tuple[str, ...] = ()

    def match_terms(self) -> tuple[str, ...]:
        # 브랜드 이름 자체도 별도 alias row 없이 매칭 대상이 되어야 한다.
        return (self.name, *self.aliases)


@dataclass(frozen=True)
class AliasMatch:
    brand_id: int
    start: int
    end: int
    matched_text: str


def _tokenize_alias(alias: str) -> list[str]:
    return [t for t in _TOKEN_SPLIT_RE.split(alias.strip()) if t]


def _is_hangul(ch: str) -> bool:
    return "가" <= ch <= "힣"


def build_alias_pattern(alias: str) -> re.Pattern[str]:
    """별칭 하나를 위 정책을 반영한 정규식으로 컴파일한다."""
    tokens = _tokenize_alias(alias)
    if not tokens:
        raise ValueError(f"빈 별칭은 매칭 패턴을 만들 수 없습니다: {alias!r}")

    body = _FLEXIBLE_SEPARATOR.join(re.escape(t) for t in tokens)
    pattern = rf"(?<![{_LATIN_ALNUM}]){body}(?![{_LATIN_ALNUM}])"

    alnum_only = "".join(tokens)
    is_all_hangul = all(_is_hangul(ch) for ch in alnum_only)
    use_case_insensitive = not (len(alnum_only) <= SHORT_ALIAS_MAX_LEN and not is_all_hangul)
    flags = re.IGNORECASE if use_case_insensitive else 0
    return re.compile(pattern, flags)


def find_all_alias_matches(text: str, brands: list[BrandForMatching]) -> list[AliasMatch]:
    """텍스트 안의 모든 별칭 매칭(브랜드당 여러 번 가능)을 등장 순서대로 반환한다.

    브랜드 이름 자체와 별칭이 토큰화 후 동일한 패턴을 만들어내는 경우(예: 이름 "Kuehne+Nagel"과
    별칭 "Kuehne nagel"은 둘 다 ["Kuehne","Nagel"]로 토큰화된다) 같은 위치가 두 번 잡힐 수 있어
    (brand_id, start, end) 기준으로 중복을 제거한다.
    """
    seen: set[tuple[int, int, int]] = set()
    matches: list[AliasMatch] = []
    for brand in brands:
        for term in brand.match_terms():
            pattern = build_alias_pattern(term)
            for m in pattern.finditer(text):
                key = (brand.id, m.start(), m.end())
                if key in seen:
                    continue
                seen.add(key)
                matches.append(
                    AliasMatch(
                        brand_id=brand.id, start=m.start(), end=m.end(), matched_text=m.group()
                    )
                )
    matches.sort(key=lambda m: m.start)
    return matches


def first_mention_per_brand(matches: list[AliasMatch]) -> list[AliasMatch]:
    """브랜드별 최초 등장 매칭만 남기고, 그 최초 등장 순서(전체 브랜드 통합 기준)로 정렬한다.

    mention_order는 이 순서(1부터)를 그대로 쓴다 — docs/metrics.md의 mention_order 정의 참조.
    """
    seen: set[int] = set()
    firsts: list[AliasMatch] = []
    for match in matches:  # matches는 이미 start 기준 정렬됨
        if match.brand_id in seen:
            continue
        seen.add(match.brand_id)
        firsts.append(match)
    return firsts
