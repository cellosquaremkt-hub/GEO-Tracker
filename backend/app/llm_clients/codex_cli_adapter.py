"""Codex CLI 어댑터 — 구독 좌석 기반 측정 채널(API 키 아님).

조사 근거: docs/llm_clis.md §2 (참고 프로젝트 20260709, 2026-07-10 확인). 인증은 `codex login`
(device-auth) 흐름으로 발급된 로컬 자격증명을 쓴다 — docs/operations.md 참조.

Codex CLI의 `--json`(JSONL 이벤트 스트림) 출력은 파싱이 번거롭고 스키마가 안정적이라고
확인되지 않았다. 대신 `-o/--output-last-message <path>`로 최종 응답 텍스트만 파일에 받는
방식을 1차 추출 수단으로 쓴다 — docs/llm_clis.md §2 참조. 토큰 수/비용은 이 경로로는 신뢰성
있게 뽑을 수 있다고 확인되지 않아 항상 None으로 둔다.
"""

from __future__ import annotations

import tempfile
import uuid
from pathlib import Path
from typing import Any

from app.core.config import settings
from app.llm_clients.base import BaseLLMAdapter, LLMResponse, retry_with_backoff
from app.llm_clients.cli_common import (
    CLIProcessError,
    CLIRateLimitError,
    CLITimeoutError,
    require_cli_installed,
    run_cli,
)
from app.llm_clients.mock import build_mock_response

# --- CLI가 바뀌면 이 블록만 고치면 된다 (docs/llm_clis.md §2 참조) ---
BINARY = "codex"
# "gpt-5-codex"는 ChatGPT 계정 로그인(API 키 아님) 기준으로 플랜에 따라 거부될 수 있다 —
# 실 CLI 파일럿(참고 프로젝트, 2026-07-13)에서 "The 'gpt-5-codex' model is not supported when
# using Codex with a ChatGPT account." 오류로 실측 확인. "gpt-5.5"는 같은 계정에서 정상 동작
# (웹 검색 + 응답 수신)까지 확인됐다. 회사 정식 계정의 플랜이 다르면(Pro/Team/Enterprise 등)
# 이 값을 다시 조정해야 할 수 있다 — docs/risk_checklist.md §4 참조.
DEFAULT_MODEL = "gpt-5.5"
# -s read-only(승인 모드)로 파일 수정/명령 실행 승인 프롬프트가 뜨지 않게 한다 — 측정 목적상
# 파일 시스템 변경은 필요 없고, headless라 프롬프트에 응답할 수도 없다. --skip-git-repo-check는
# 필수다: CLI_WORKDIR가 git 저장소가 아니면(의도된 설계 — 전용 빈 디렉터리) Codex CLI가 "Not
# inside a trusted directory"로 즉시 거부하는 것을 실측으로 확인했다.
# `--search`는 뺐다: 실 CLI 파일럿(2026-07-13, Codex CLI v0.144.1)에서 이 버전은 그 플래그
# 자체를 모르고("error: unexpected argument '--search' found") 즉시 거부하는 것을 확인했다.
# 같은 버전으로 `--search` 없이 수동 테스트했을 때 실제로 웹 검색을 수행하는 것도 확인됨 — 이
# 버전은 웹 검색이 기본으로 켜져 있는 것으로 보인다(docs/llm_clis.md §2(b) 참조).
WEB_SEARCH_ENABLED = True
BASE_ARGS: list[str] = ["-s", "read-only", "--skip-git-repo-check"]
RETRYABLE_EXCEPTIONS: tuple[type[Exception], ...] = (
    CLITimeoutError,
    CLIProcessError,
    CLIRateLimitError,
)
LONG_DELAY_EXCEPTIONS: tuple[type[Exception], ...] = (CLIRateLimitError,)
MAX_RETRY_ATTEMPTS = 4
BASE_DELAY_SECONDS = 2.0
# ------------------------------------------------------------------------


class CodexCLIAdapter(BaseLLMAdapter):
    provider_name = "codex-cli"

    def __init__(self, model: str | None = None) -> None:
        self._model = model or DEFAULT_MODEL

    def query(self, prompt: str) -> LLMResponse:
        if settings.mock_llm:
            return build_mock_response(self.provider_name, self._model, prompt)

        require_cli_installed(BINARY, provider_name=self.provider_name)

        # CLI_WORKDIR 안에 매 호출마다 새 이름으로 만든다 — 동시 실행 중인 다른 codex 호출과
        # 출력 파일이 겹치지 않게 하기 위해서다.
        output_path = Path(tempfile.gettempdir()) / f"geo-tracker-codex-{uuid.uuid4().hex}.txt"
        args = [
            BINARY,
            "exec",
            "-m",
            self._model,
            *BASE_ARGS,
            "-o",
            str(output_path),
            prompt,
        ]

        def _call() -> Any:
            return run_cli(
                args, provider_name=self.provider_name, timeout_seconds=settings.cli_timeout_sec
            )

        try:
            retry_with_backoff(
                _call,
                retryable_exceptions=RETRYABLE_EXCEPTIONS,
                long_delay_exceptions=LONG_DELAY_EXCEPTIONS,
                max_attempts=MAX_RETRY_ATTEMPTS,
                base_delay_seconds=BASE_DELAY_SECONDS,
                provider_name=self.provider_name,
            )
            if output_path.exists():
                text = output_path.read_text(encoding="utf-8", errors="replace")
            else:
                text = ""
        finally:
            output_path.unlink(missing_ok=True)

        return LLMResponse(
            text=text.strip(),
            # CLI는 구조화된 citation을 반환하지 않는다 — 파싱 엔진의 본문 URL 정규식 폴백이 주
            # 수단이 된다 (docs/llm_clis.md §3, 3-1 파싱 엔진).
            citations=[],
            # --search로 도구가 허용되어 있었는지의 근사치다 — 실제 이번 호출에서 검색했는지는
            # -o로 받는 최종 텍스트만으로는 확인할 수 없다 (docs/llm_clis.md §2 알려진 한계).
            web_search_used=WEB_SEARCH_ENABLED,
            input_tokens=None,
            output_tokens=None,
            cost_usd=None,
            model_string=self._model,
        )
