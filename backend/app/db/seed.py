"""로컬/개발 환경용 초기 데이터 시딩. 브랜드·별칭·도메인·LLM 프로바이더·프롬프트를 채운다.

실행: python -m app.db.seed  (backend/ 디렉터리에서, venv 활성화 후)

이름/텍스트 기준으로 존재 여부를 확인하고 없을 때만 추가하므로 여러 번 실행해도 안전하다
(idempotent).
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.db.session import SessionLocal
from app.models.brand import Brand, BrandAlias, BrandDomain
from app.models.enums import Language, Priority, Target
from app.models.llm_provider import LLMProvider
from app.models.prompt import Prompt

_REPO_ROOT = Path(__file__).resolve().parents[3]
KEYWORDS_PATH = _REPO_ROOT / "data" / "keywords.json"

OWN_BRANDS: list[dict[str, Any]] = [
    {"name": "삼성SDS", "aliases": ["Samsung SDS", "삼성 SDS"], "domains": ["samsungsds.com"]},
    {
        "name": "첼로스퀘어",
        "aliases": ["Cello Square", "첼로 스퀘어"],
        "domains": ["cellosquare.com"],
    },
]

COMPETITOR_BRANDS: list[dict[str, Any]] = [
    {"name": "LX Pantos", "aliases": ["LX판토스", "판토스"], "domains": ["lxpantos.com"]},
    {"name": "Flexport", "aliases": [], "domains": ["flexport.com"]},
    {
        "name": "Kuehne+Nagel",
        "aliases": ["Kuehne nagel", "K+N", "퀴네나겔"],
        "domains": ["kuehne-nagel.com"],
    },
    {"name": "Tradlinx", "aliases": ["트레드링스"], "domains": ["tradlinx.com"]},
    {"name": "DHL", "aliases": ["DHL Global Forwarding"], "domains": ["dhl.com"]},
]

# STEP 6부터 회사 사정으로 API 키 발급이 막혀 SDK 기반 채널을 비활성화하고 구독 좌석 CLI로
# 전환했다(docs/llm_clis.md 참조). 과거 실행 이력(execution_run 등)의 프로바이더 참조가 깨지지
# 않도록 레거시 행은 지우지 않고 is_active=False로만 내린다. model_string은 각 어댑터의
# DEFAULT_MODEL과 맞춘다.
LLM_PROVIDERS: list[dict[str, Any]] = [
    # --- Legacy(SDK/API 키) — STEP 6부터 비활성. app/llm_clients/legacy/ 참조.
    {
        "name": "ChatGPT",
        "model_string": "gpt-5.4",
        "supports_web_search": True,
        "is_active": False,
    },
    {
        "name": "Gemini",
        "model_string": "gemini-3.5-flash",
        "supports_web_search": True,
        "is_active": False,
    },
    {
        "name": "Perplexity",
        "model_string": "sonar-pro",
        "supports_web_search": True,
        "is_active": False,
    },
    {
        "name": "Claude",
        "model_string": "claude-sonnet-5",
        "supports_web_search": True,
        "is_active": False,
    },
    # --- CLI 기반(STEP 6, 구독 좌석) — 현재 활성 측정 채널. docs/llm_clis.md 참조.
    # Perplexity는 CLI가 없어 대체 채널 없이 제외된다.
    {
        "name": "claude-code-cli",
        "model_string": "sonnet",
        "supports_web_search": True,
        "is_active": True,
    },
    {
        "name": "codex-cli",
        # ChatGPT 계정 로그인(API 키 아님) 기준 "gpt-5-codex"가 플랜에 따라 거부될 수 있음을
        # 실 CLI 파일럿(2026-07-13)에서 확인 — codex_cli_adapter.py 상단 주석 참조. 회사 정식
        # 계정의 플랜이 다르면 이 값을 다시 조정해야 할 수 있다(docs/risk_checklist.md §4).
        "model_string": "gpt-5.5",
        "supports_web_search": True,
        "is_active": True,
    },
    {
        "name": "gemini-cli",
        "model_string": "gemini-2.5-pro",
        "supports_web_search": True,
        "is_active": True,
    },
]


def _get_or_create_brand(session: Session, name: str, is_own: bool) -> Brand:
    brand = session.execute(select(Brand).where(Brand.name == name)).scalar_one_or_none()
    if brand is not None:
        return brand
    brand = Brand(name=name, is_own=is_own)
    session.add(brand)
    session.flush()
    return brand


def _sync_aliases(session: Session, brand: Brand, aliases: list[str]) -> None:
    existing = set(
        session.execute(
            select(BrandAlias.alias_text).where(BrandAlias.brand_id == brand.id)
        ).scalars()
    )
    for alias_text in aliases:
        if alias_text not in existing:
            session.add(BrandAlias(brand_id=brand.id, alias_text=alias_text))


def _sync_domains(session: Session, brand: Brand, domains: list[str]) -> None:
    existing = set(
        session.execute(
            select(BrandDomain.domain).where(BrandDomain.brand_id == brand.id)
        ).scalars()
    )
    for domain in domains:
        if domain not in existing:
            session.add(BrandDomain(brand_id=brand.id, domain=domain))


def seed_brands(session: Session) -> None:
    for entry in OWN_BRANDS:
        brand = _get_or_create_brand(session, entry["name"], is_own=True)
        _sync_aliases(session, brand, entry["aliases"])
        _sync_domains(session, brand, entry["domains"])
    for entry in COMPETITOR_BRANDS:
        brand = _get_or_create_brand(session, entry["name"], is_own=False)
        _sync_aliases(session, brand, entry["aliases"])
        _sync_domains(session, brand, entry["domains"])


def seed_llm_providers(session: Session) -> None:
    """LLM_PROVIDERS를 채우거나 갱신한다.

    브랜드/프롬프트 시딩과 달리 여기서는 이미 존재하는 행의 is_active도 맞춰준다 — STEP 6
    전환 시 이미 DB에 들어있던 레거시 프로바이더 행을 is_active=False로 내려야 하는데,
    "없을 때만 추가"만으로는 기존 행이 갱신되지 않기 때문이다.
    """
    for entry in LLM_PROVIDERS:
        provider = session.execute(
            select(LLMProvider).where(LLMProvider.name == entry["name"])
        ).scalar_one_or_none()
        if provider is None:
            session.add(
                LLMProvider(
                    name=entry["name"],
                    model_string=entry["model_string"],
                    supports_web_search=entry["supports_web_search"],
                    is_active=entry["is_active"],
                )
            )
            continue
        provider.is_active = entry["is_active"]


def _load_keyword_prompts() -> list[dict[str, Any]]:
    if not KEYWORDS_PATH.exists():
        raise FileNotFoundError(
            f"{KEYWORDS_PATH} 가 없습니다. data/keywords.json을 먼저 준비하세요 "
            "(스키마는 파일 안의 _note 필드 참조)."
        )
    payload = json.loads(KEYWORDS_PATH.read_text(encoding="utf-8"))
    return payload["prompts"]


def seed_prompts(session: Session) -> None:
    for entry in _load_keyword_prompts():
        existing = session.execute(
            select(Prompt).where(Prompt.text == entry["text"])
        ).scalar_one_or_none()
        if existing is not None:
            continue
        session.add(
            Prompt(
                text=entry["text"],
                intent=entry["intent"],
                target=Target(entry["target"]),
                priority=Priority(entry["priority"]),
                language=Language(entry["language"]),
            )
        )


def run_seed() -> None:
    session = SessionLocal()
    try:
        seed_brands(session)
        seed_llm_providers(session)
        seed_prompts(session)
        session.commit()
    finally:
        session.close()


if __name__ == "__main__":
    run_seed()
