"""CLI 어댑터(Claude Code/Codex/Gemini CLI) 단위 테스트 (동기).

subprocess는 항상 mock으로 대체한다 — CLAUDE.md 규칙("실제 CLI 호출 테스트 금지")과
app/llm_clients/cli_common.py의 run_cli()가 유일한 진입점이라는 점을 이용해, run_cli 또는 그
아래의 subprocess.Popen만 패치하면 실제 프로세스를 띄우지 않고 파싱/재시도/오류 분류 로직을
검증할 수 있다.
"""

from __future__ import annotations

import json
import subprocess
from decimal import Decimal
from pathlib import Path

import pytest

from app.core.config import settings
from app.llm_clients.base import LLMAdapterError, MissingAPIKeyError
from app.llm_clients.claude_code_cli_adapter import ClaudeCodeCLIAdapter
from app.llm_clients.claude_code_cli_adapter import _parse_stdout as parse_claude_code_stdout
from app.llm_clients.cli_common import (
    CLIProcessError,
    CLIRateLimitError,
    CLIResult,
    CLITimeoutError,
    CLIWorkdirNotEmptyError,
    ensure_workdir_ready,
    require_cli_installed,
    run_cli,
)
from app.llm_clients.codex_cli_adapter import CodexCLIAdapter
from app.llm_clients.gemini_cli_adapter import GeminiCLIAdapter
from app.llm_clients.gemini_cli_adapter import _parse_stdout as parse_gemini_stdout
from app.services.citation_extraction import resolve_citations


class _FakePopen:
    def __init__(self, stdout: bytes, stderr: bytes, returncode: int) -> None:
        self._stdout = stdout
        self._stderr = stderr
        self.returncode = returncode
        self.killed = False
        self.pid = 999999

    def communicate(self, timeout: float | None = None) -> tuple[bytes, bytes]:
        return self._stdout, self._stderr

    def kill(self) -> None:
        self.killed = True

    def wait(self, timeout: float | None = None) -> int:
        return self.returncode


@pytest.fixture(autouse=True)
def _mock_mode_off(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(settings, "mock_llm", False)


@pytest.fixture
def _empty_workdir(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    workdir = tmp_path / "cli-workdir"
    monkeypatch.setattr(settings, "cli_workdir", str(workdir))
    return workdir


class TestEnsureWorkdirReady:
    def test_creates_missing_dir(self, tmp_path: Path) -> None:
        workdir = tmp_path / "does-not-exist-yet"
        ensure_workdir_ready(workdir)
        assert workdir.is_dir()

    def test_raises_when_not_empty(self, tmp_path: Path) -> None:
        workdir = tmp_path / "dirty"
        workdir.mkdir()
        (workdir / "leftover.txt").write_text("x", encoding="utf-8")
        with pytest.raises(CLIWorkdirNotEmptyError):
            ensure_workdir_ready(workdir)


class TestRequireCliInstalled:
    def test_raises_when_binary_missing(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setattr("shutil.which", lambda _binary: None)
        with pytest.raises(MissingAPIKeyError):
            require_cli_installed("definitely-not-a-real-binary", provider_name="test")

    def test_passes_when_binary_found(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setattr("shutil.which", lambda _binary: "/usr/bin/fake")
        require_cli_installed("fake", provider_name="test")  # 예외 없이 통과해야 한다


class TestRunCli:
    def test_success_returns_cli_result(
        self, _empty_workdir: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        def _fake_popen(*_args: object, **_kwargs: object) -> _FakePopen:
            return _FakePopen(b"stdout-ok", b"", 0)

        monkeypatch.setattr(subprocess, "Popen", _fake_popen)
        result = run_cli(["echo", "hi"], provider_name="test")
        assert result == CLIResult(stdout="stdout-ok", stderr="", exit_code=0)

    def test_timeout_raises_and_kills_process(
        self, _empty_workdir: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        fake_process = _FakePopen(b"", b"", 0)

        def _hang(timeout: float | None = None) -> tuple[bytes, bytes]:
            raise subprocess.TimeoutExpired(cmd=["sleep"], timeout=timeout or 0)

        fake_process.communicate = _hang  # type: ignore[method-assign]

        def _fake_popen(*_args: object, **_kwargs: object) -> _FakePopen:
            return fake_process

        monkeypatch.setattr(subprocess, "Popen", _fake_popen)
        with pytest.raises(CLITimeoutError):
            run_cli(["sleep", "999"], provider_name="test", timeout_seconds=0.01)
        assert fake_process.killed

    def test_nonzero_exit_with_auth_pattern_raises_missing_api_key(
        self, _empty_workdir: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        def _fake_popen(*_args: object, **_kwargs: object) -> _FakePopen:
            stderr = b"Error: not authenticated. Please run `claude setup-token`."
            return _FakePopen(b"", stderr, 1)

        monkeypatch.setattr(subprocess, "Popen", _fake_popen)
        with pytest.raises(MissingAPIKeyError):
            run_cli(["claude"], provider_name="test")

    def test_nonzero_exit_with_rate_limit_pattern_raises_rate_limit_error(
        self, _empty_workdir: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        def _fake_popen(*_args: object, **_kwargs: object) -> _FakePopen:
            return _FakePopen(b"", b"You've hit your usage limit for this period.", 1)

        monkeypatch.setattr(subprocess, "Popen", _fake_popen)
        with pytest.raises(CLIRateLimitError):
            run_cli(["codex"], provider_name="test")

    def test_nonzero_exit_generic_raises_process_error(
        self, _empty_workdir: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        def _fake_popen(*_args: object, **_kwargs: object) -> _FakePopen:
            return _FakePopen(b"", b"boom: segfault", 1)

        monkeypatch.setattr(subprocess, "Popen", _fake_popen)
        with pytest.raises(CLIProcessError):
            run_cli(["gemini"], provider_name="test")


class TestClaudeCodeStdoutParsing:
    def test_parses_result_usage_and_cost(self) -> None:
        stdout = json.dumps(
            {
                "result": "첼로스퀘어는 국내 선도 서비스입니다.",
                "is_error": False,
                "usage": {"input_tokens": 120, "output_tokens": 340},
                "total_cost_usd": 0.0087,
            }
        )
        response = parse_claude_code_stdout(stdout, "sonnet")
        assert response.text == "첼로스퀘어는 국내 선도 서비스입니다."
        assert response.citations == []
        assert response.web_search_used is True
        assert response.input_tokens == 120
        assert response.output_tokens == 340
        assert response.cost_usd == Decimal("0.0087")
        assert response.model_string == "sonnet"

    def test_is_error_true_raises(self) -> None:
        stdout = json.dumps({"result": "실패했습니다", "is_error": True})
        with pytest.raises(LLMAdapterError):
            parse_claude_code_stdout(stdout, "sonnet")

    def test_invalid_json_raises(self) -> None:
        with pytest.raises(LLMAdapterError):
            parse_claude_code_stdout("not json at all", "sonnet")

    def test_missing_cost_field_defaults_to_none(self) -> None:
        stdout = json.dumps({"result": "ok", "is_error": False, "usage": {}})
        response = parse_claude_code_stdout(stdout, "sonnet")
        assert response.cost_usd is None
        assert response.input_tokens is None
        assert response.output_tokens is None


class TestClaudeCodeAdapterQuery:
    def test_query_invokes_run_cli_and_parses(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setattr("shutil.which", lambda _binary: "/usr/bin/claude")
        stdout = json.dumps(
            {"result": "hello", "is_error": False, "usage": {"input_tokens": 1, "output_tokens": 2}}
        )

        def _fake_run_cli(*_args: object, **_kwargs: object) -> CLIResult:
            return CLIResult(stdout=stdout, stderr="", exit_code=0)

        monkeypatch.setattr("app.llm_clients.claude_code_cli_adapter.run_cli", _fake_run_cli)
        adapter = ClaudeCodeCLIAdapter()
        response = adapter.query("테스트 프롬프트")
        assert response.text == "hello"
        assert response.citations == []

    def test_mock_mode_never_touches_subprocess(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setattr(settings, "mock_llm", True)

        def _boom(*_args: object, **_kwargs: object) -> None:
            raise AssertionError("MOCK_LLM=true인데 실제 subprocess를 띄우려 했다")

        monkeypatch.setattr(subprocess, "Popen", _boom)
        adapter = ClaudeCodeCLIAdapter()
        response = adapter.query("test prompt")
        assert response.text
        assert response.citations == []


class TestCodexAdapterQuery:
    def test_query_reads_output_file_and_cleans_up(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setattr("shutil.which", lambda _binary: "/usr/bin/codex")
        written_path: dict[str, Path] = {}

        def _fake_run_cli(args: list[str], **_kwargs: object) -> CLIResult:
            output_path = Path(args[args.index("-o") + 1])
            output_path.write_text("최종 응답 텍스트", encoding="utf-8")
            written_path["path"] = output_path
            return CLIResult(stdout="", stderr="", exit_code=0)

        monkeypatch.setattr("app.llm_clients.codex_cli_adapter.run_cli", _fake_run_cli)
        adapter = CodexCLIAdapter()
        response = adapter.query("테스트 프롬프트")

        assert response.text == "최종 응답 텍스트"
        assert response.citations == []
        assert response.input_tokens is None
        assert response.output_tokens is None
        assert response.cost_usd is None
        assert not written_path["path"].exists()  # finally 블록에서 정리됐어야 한다

    def test_missing_output_file_yields_empty_text(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setattr("shutil.which", lambda _binary: "/usr/bin/codex")

        def _fake_run_cli(*_args: object, **_kwargs: object) -> CLIResult:
            return CLIResult(stdout="", stderr="", exit_code=0)

        monkeypatch.setattr("app.llm_clients.codex_cli_adapter.run_cli", _fake_run_cli)
        adapter = CodexCLIAdapter()
        response = adapter.query("테스트 프롬프트")
        assert response.text == ""


class TestGeminiStdoutParsing:
    def test_parses_response_and_tokens(self) -> None:
        stdout = json.dumps(
            {
                "response": "Cello Square is a leading platform.",
                "stats": {
                    "models": {"gemini-2.5-pro": {"tokens": {"prompt": 50, "candidates": 200}}},
                    "tools": {"google_web_search": {"count": 1}},
                },
            }
        )
        response = parse_gemini_stdout(stdout, "gemini-2.5-pro")
        assert response.text == "Cello Square is a leading platform."
        assert response.citations == []
        assert response.input_tokens == 50
        assert response.output_tokens == 200
        assert response.web_search_used is True

    def test_no_tool_stats_falls_back_to_enabled_constant(self) -> None:
        stdout = json.dumps({"response": "no stats here"})
        response = parse_gemini_stdout(stdout, "gemini-2.5-pro")
        assert response.web_search_used is True
        assert response.input_tokens is None
        assert response.output_tokens is None

    def test_zero_search_count_means_not_used(self) -> None:
        stdout = json.dumps(
            {"response": "ok", "stats": {"tools": {"google_web_search": {"count": 0}}}}
        )
        response = parse_gemini_stdout(stdout, "gemini-2.5-pro")
        assert response.web_search_used is False

    def test_error_field_raises(self) -> None:
        stdout = json.dumps({"error": {"message": "boom"}})
        with pytest.raises(LLMAdapterError):
            parse_gemini_stdout(stdout, "gemini-2.5-pro")

    def test_invalid_json_raises(self) -> None:
        with pytest.raises(LLMAdapterError):
            parse_gemini_stdout("{not json", "gemini-2.5-pro")


class TestGeminiAdapterQuery:
    def test_mock_mode_never_touches_subprocess(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setattr(settings, "mock_llm", True)

        def _boom(*_args: object, **_kwargs: object) -> None:
            raise AssertionError("MOCK_LLM=true인데 실제 subprocess를 띄우려 했다")

        monkeypatch.setattr(subprocess, "Popen", _boom)
        adapter = GeminiCLIAdapter()
        response = adapter.query("test prompt")
        assert response.text


class TestCitationRegexFallbackForCliMocks:
    """CLI 목 응답은 citations=[]이지만 본문에 URL이 박혀있다 — 정규식 폴백이 실제로 그 URL을
    뽑아내는지 확인한다."""

    @pytest.mark.parametrize("provider_name", ["claude-code-cli", "codex-cli", "gemini-cli"])
    def test_regex_fallback_extracts_urls_from_mock_text(
        self, provider_name: str, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setattr(settings, "mock_llm", True)
        from app.llm_clients.factory import get_adapter

        adapter = get_adapter(provider_name)
        response = adapter.query("첼로스퀘어와 경쟁사를 비교해줘")
        assert response.citations == []

        resolved = resolve_citations(
            adapter_citations=response.citations, response_text=response.text
        )
        assert resolved, f"{provider_name}: 정규식 폴백이 URL을 하나도 못 뽑았다"
        assert all(url.startswith("https://") for url in resolved)
