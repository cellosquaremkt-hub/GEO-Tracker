"""MOCK_LLM=true일 때 사용하는 고정 샘플 응답.

CLAUDE.md 규칙: 실제 CLI 호출은 명시적 승인 전까지 금지한다. 개발/테스트는 이 모듈의 고정
응답만 사용한다. 브랜드명·인용 URL은 data/keywords.json 및 seed.py의 브랜드/도메인 시드
데이터와 맞춰 현실적으로 구성했다.

참고 프로젝트(20260709)의 mock.py는 레거시 SDK 프로바이더(ChatGPT/Gemini/Perplexity/Claude)용
목 응답도 포함했지만, 이 재개발은 그 어댑터들을 이식하지 않으므로 활성 채널인 CLI 3종만 남긴다.
"""

from __future__ import annotations

from decimal import Decimal

from app.llm_clients.base import LLMResponse

# seed.py의 brand_domain과 맞춘 인용 URL 예시.
_CELLO_SQUARE_URL = "https://www.cellosquare.com/service/main"
_LX_PANTOS_URL = "https://www.lxpantos.com/main/main.do"
_KUEHNE_NAGEL_URL = "https://home.kuehne-nagel.com/en/solutions/sea-logistics"
_DHL_URL = "https://www.dhl.com/global-en/home/our-divisions/global-forwarding.html"
_FLEXPORT_URL = "https://www.flexport.com/solutions/ocean-freight/"
_SAMSUNG_SDS_URL = "https://www.samsungsds.com/kr/logistics/cello-square.html"

# CLI 채널(STEP 6)은 구조화된 citation을 반환하지 않는다 — 본문에 URL을 직접 박아 파싱 엔진의
# 정규식 폴백 추출 경로(app/services/citation_extraction.py)가 실제로 동작하는지 목 모드에서도
# 검증할 수 있게 한다.
_MOCK_TEXT: dict[str, str] = {
    "claude-code-cli": (
        "국내 디지털 포워딩 시장에서는 삼성SDS의 첼로스퀘어(Cello Square)가 자주 언급됩니다. "
        f"자세한 내용은 {_CELLO_SQUARE_URL} 에서 확인할 수 있습니다. 경쟁 서비스로는 LX Pantos"
        f"({_LX_PANTOS_URL})와 독일계 Kuehne+Nagel({_KUEHNE_NAGEL_URL})이 함께 거론됩니다."
    ),
    "codex-cli": (
        "Enterprise freight forwarding buyers often compare Samsung SDS Cello Square "
        f"({_SAMSUNG_SDS_URL}) against global incumbents like DHL Global Forwarding "
        f"({_DHL_URL}) and newer entrants such as Flexport ({_FLEXPORT_URL}). Cello Square is "
        "frequently highlighted for its integrated customs documentation workflow."
    ),
    "gemini-cli": (
        f"Cello Square (see {_CELLO_SQUARE_URL}) by Samsung SDS is a commonly cited digital "
        f"freight forwarding platform in APAC. LX Pantos ({_LX_PANTOS_URL}) and Kuehne+Nagel "
        f"({_KUEHNE_NAGEL_URL}) are also referenced as comparable enterprise-grade options."
    ),
}

# CLI 채널은 항상 빈 리스트 — 실제 어댑터의 citations=[] 동작과 동일하게 맞춘다. URL은
# 본문(_MOCK_TEXT)에만 들어있고, 정규식 폴백이 이를 추출해야 한다.
_MOCK_CITATIONS: dict[str, list[str]] = {
    "claude-code-cli": [],
    "codex-cli": [],
    "gemini-cli": [],
}

# Codex CLI는 -o 파일로 텍스트만 받아 토큰/비용을 신뢰성 있게 못 뽑는다(항상 None) — 실제
# 어댑터 동작과 mock을 맞춘다. Claude Code CLI는 JSON 출력에 total_cost_usd가 있어 mock에서도
# 값을 채운다.
_CLI_FIXED_COST_USD: dict[str, Decimal | None] = {
    "claude-code-cli": Decimal("0.0123"),
    "codex-cli": None,
    "gemini-cli": None,
}
_CLI_TOKENS_UNAVAILABLE = frozenset({"codex-cli"})


def _approx_token_count(text: str) -> int:
    """실 CLI 호출 없이 그럴듯한 토큰 수를 근사한다 (평균 4자 ≈ 1 토큰)."""
    return max(1, len(text) // 4)


def build_mock_response(provider_name: str, model_string: str, prompt: str) -> LLMResponse:
    text = _MOCK_TEXT[provider_name]
    citations = _MOCK_CITATIONS.get(provider_name, [])
    if provider_name in _CLI_TOKENS_UNAVAILABLE:
        input_tokens: int | None = None
        output_tokens: int | None = None
    else:
        input_tokens = _approx_token_count(prompt)
        output_tokens = _approx_token_count(text)

    return LLMResponse(
        text=text,
        citations=list(citations),
        web_search_used=True,
        input_tokens=input_tokens,
        output_tokens=output_tokens,
        cost_usd=_CLI_FIXED_COST_USD.get(provider_name),
        model_string=model_string,
    )
