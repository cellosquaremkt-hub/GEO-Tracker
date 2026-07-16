"""CLI 기반 어댑터(Claude Code/Codex/Gemini CLI) 공통 subprocess 실행 유틸 (동기).

세 어댑터 모두 이 모듈의 run_cli()로 프로세스를 띄운다 — 작업 디렉터리 가드, 타임아웃, 비정상
종료 분류(인증/레이트리밋/일반 오류)를 한 곳에서 관리해 어댑터마다 중복하지 않는다.

**이 모듈은 worker 데몬 프로세스(app/worker/daemon.py) 안에서만 쓰인다 — Flask 웹 앱은 CLI
서브프로세스를 절대 실행하지 않는다**(migration_flask_postgres.md §2.3 참조).
"""

from __future__ import annotations

import os
import shutil
import signal
import subprocess
from dataclasses import dataclass
from pathlib import Path

from app.core.config import settings
from app.llm_clients.base import LLMAdapterError, MissingAPIKeyError


def _prepend_known_cli_install_dirs() -> None:
    """CLI 설치 도구가 쓰는 잘 알려진 디렉터리를 이 프로세스의 PATH 맨 앞에 추가한다 (Windows 전용).

    참고 프로젝트(20260709, Windows)에서 실측으로 확인된 PATH 갱신 지연 문제에 대한 방어다.
    Ubuntu 배포 환경에서는 CLI 설치 경로를 worker 데몬의 systemd 유닛 `Environment=PATH=...`에
    명시하는 방식을 우선한다(migration_flask_postgres.md §6) — 이 함수는 os.name이 "nt"가 아니면
    아무 것도 하지 않는 안전망으로만 남겨둔다.
    """
    if os.name != "nt":
        return
    known_dirs = [str(Path.home() / ".local" / "bin")]
    appdata = os.environ.get("APPDATA")
    if appdata:
        known_dirs.append(str(Path(appdata) / "npm"))
    current_path = os.environ.get("PATH", "")
    os.environ["PATH"] = os.pathsep.join([*known_dirs, current_path])


_prepend_known_cli_install_dirs()

# 사용량 한도(구독 좌석 rate limit) 메시지에서 흔히 보이는 패턴 — docs/llm_clis.md §4
# (Codex "You've hit your usage limit" 등 실제 확인된 문구 포함). 대소문자 무시로 비교한다.
_RATE_LIMIT_PATTERNS: tuple[str, ...] = (
    "usage limit",
    "rate limit",
    "rate_limit",
    "too many requests",
    "quota",
    "429",
)

# 인증 관련 실패로 보이는 패턴 — 재시도해도 성공할 수 없으므로 MissingAPIKeyError로 승격한다.
_AUTH_ERROR_PATTERNS: tuple[str, ...] = (
    "not logged in",
    "not authenticated",
    "unauthorized",
    "authentication",
    "please log in",
    "please run",
    "auth failed",
    "oauth",
)


class CLIWorkdirNotEmptyError(LLMAdapterError):
    """CLI_WORKDIR가 비어 있지 않을 때 — 다른 프로젝트/이전 실행 잔여물과 섞이는 것을 막는다."""


class CLITimeoutError(LLMAdapterError):
    """CLI_TIMEOUT_SEC 안에 프로세스가 끝나지 않았을 때. 재시도 대상."""


class CLIProcessError(LLMAdapterError):
    """CLI가 0이 아닌 종료 코드로 끝났을 때(인증/레이트리밋이 아닌 일반 오류). 재시도 대상."""


class CLIRateLimitError(CLIProcessError):
    """stdout/stderr에서 사용량 한도류 문구를 감지했을 때 — 더 긴 백오프로 재시도한다."""


@dataclass(frozen=True)
class CLIResult:
    stdout: str
    stderr: str
    exit_code: int


def ensure_workdir_ready(workdir: Path) -> None:
    """CLI_WORKDIR가 없으면 만들고, 있으면 비어 있는지 확인한다.

    이 디렉터리는 프로젝트와 무관한 전용 빈 폴더여야 한다 — 실행 디렉터리의 CLAUDE.md/
    AGENTS.md 등 프로젝트 컨텍스트가 답변에 섞여 측정값을 오염시키는 것을 막기 위해서다.
    채워져 있으면 잘못된 디렉터리가 설정됐거나 이전 실행이 뭔가를 남긴 것이므로, 조용히
    진행하지 않고 즉시 실패시켜 조기에 알아챌 수 있게 한다.
    """
    workdir.mkdir(parents=True, exist_ok=True)
    if any(workdir.iterdir()):
        raise CLIWorkdirNotEmptyError(
            f"CLI_WORKDIR '{workdir}'가 비어 있지 않습니다. 프로젝트와 무관한 전용 빈 "
            "디렉터리를 가리키는지 확인하세요 (.env의 CLI_WORKDIR)."
        )


def require_cli_installed(binary: str, *, provider_name: str) -> None:
    if shutil.which(binary) is None:
        raise MissingAPIKeyError(
            f"{provider_name}: '{binary}' 실행 파일을 PATH에서 찾을 수 없습니다. 설치와 "
            f"로그인 상태(docs/operations.md)를 확인하세요. MOCK_LLM=true면 이 검사는 "
            "실행되지 않습니다."
        )


def _matches_any(text: str, patterns: tuple[str, ...]) -> bool:
    lowered = text.lower()
    return any(pattern in lowered for pattern in patterns)


def _kill_process_group(process: subprocess.Popen[bytes]) -> None:
    """타임아웃 시 자식이 띄운 손자 프로세스까지 포함해 프로세스 그룹 전체를 죽인다.

    `process.kill()`만 하면 CLI가 내부적으로 띄운 Node 자식 프로세스가 좀비로 남을 수 있다 —
    반복 배치 환경에서는 이게 누적되어 서버 자원을 고갈시키므로 선택 사항이 아니라 필수
    구현이다(migration_flask_postgres.md §6, Opus 4.8 검증 M-2). `os.killpg`/`os.getpgid`는
    POSIX 전용(배포 대상 Ubuntu)이라 이 경로를 쓰고, 그 함수들이 없는 환경(Windows 개발 PC)에서는
    안전망으로 `process.kill()`에 폴백한다 — 이 폴백 경로는 손자 프로세스를 정리하지 못하므로
    운영 환경(Ubuntu)에서는 항상 os.killpg 경로를 타야 한다.
    """
    if hasattr(os, "killpg") and hasattr(os, "getpgid"):
        try:
            os.killpg(os.getpgid(process.pid), signal.SIGKILL)
        except ProcessLookupError:
            pass
    else:
        process.kill()


def run_cli(
    args: list[str],
    *,
    provider_name: str,
    timeout_seconds: float | None = None,
) -> CLIResult:
    """subprocess.Popen으로 CLI를 실행하고 stdout/stderr/exit_code를 반환한다.

    `start_new_session=True`로 띄워 새 세션(POSIX: setsid)을 만든다 — 타임아웃 시
    `_kill_process_group()`이 프로세스 그룹 전체를 죽일 수 있게 하기 위해서다.

    실패를 세 종류로 분류해 서로 다른 예외로 던진다 — 호출자는 이걸 retry_with_backoff의
    retryable_exceptions(일반)와 long_delay_exceptions(레이트리밋)에 등록해 재시도 정책을
    나눈다:
    - 인증 실패로 보이면 MissingAPIKeyError (재시도하지 않음)
    - 사용량 한도로 보이면 CLIRateLimitError (긴 간격으로 재시도)
    - 그 외 비정상 종료/타임아웃은 CLIProcessError/CLITimeoutError (일반 간격으로 재시도)
    """
    workdir = Path(settings.cli_workdir)
    ensure_workdir_ready(workdir)
    timeout = timeout_seconds if timeout_seconds is not None else settings.cli_timeout_sec

    process = subprocess.Popen(
        args,
        cwd=str(workdir),
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        start_new_session=True,
    )
    try:
        stdout_bytes, stderr_bytes = process.communicate(timeout=timeout)
    except subprocess.TimeoutExpired:
        _kill_process_group(process)
        process.wait()
        raise CLITimeoutError(
            f"{provider_name}: {timeout}초 안에 응답하지 않아 종료했습니다 (CLI_TIMEOUT_SEC)."
        ) from None

    stdout = stdout_bytes.decode("utf-8", errors="replace")
    stderr = stderr_bytes.decode("utf-8", errors="replace")
    exit_code = process.returncode or 0

    if exit_code != 0:
        combined = f"{stdout}\n{stderr}"
        message = f"{provider_name}: 종료 코드 {exit_code}. stderr: {stderr[:2000]}"
        if _matches_any(combined, _AUTH_ERROR_PATTERNS):
            raise MissingAPIKeyError(message)
        if _matches_any(combined, _RATE_LIMIT_PATTERNS):
            raise CLIRateLimitError(message)
        raise CLIProcessError(message)

    return CLIResult(stdout=stdout, stderr=stderr, exit_code=exit_code)
