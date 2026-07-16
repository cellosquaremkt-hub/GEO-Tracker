# LLM CLI 조사 (구독 좌석 기반 측정 채널)

회사 사정으로 각 AI사의 API 키를 발급받을 수 없어, 데이터 수집은 SDK 기반 API 호출이 아니라
구독 좌석 기반 코딩 에이전트 CLI 호출로 이루어진다. 이 문서는 참고 프로젝트(20260709)의 CLI
조사 내용을 그대로 옮긴 것이다 — CLI별 명령행/응답 스키마/인증 방식 등 **CLI 자체의 사실**은
프레임워크(FastAPI→Flask)나 OS(Windows→Ubuntu)가 바뀌어도 그대로 유지된다. §7만 Ubuntu 실행
환경에 맞춰 새로 썼다.

**조사일: 2026-07-10, 실 CLI 파일럿: 2026-07-13(참고 프로젝트, Windows).** CLI는 API보다 훨씬
자주 바뀐다(버전 업데이트마다 플래그가 추가/변경될 수 있음) — 어댑터 코드를 수정하기 전에는 이
문서보다 각 CLI의 `--help`/공식 문서를 우선한다. 이 문서와 실제 CLI 동작이 다르면 이 문서를
먼저 갱신한다.

## 0. 측정 채널

| | 채널 | 인증 |
|---|---|---|
| 활성 | Claude Code CLI / Codex CLI / Gemini CLI (구독 좌석) | 각 CLI의 로컬 로그인 상태 (docs/operations.md 참조) |
| 제외 | Perplexity | 전용 CLI가 없음 |

**측정 채널의 성격을 명확히 인지해야 한다.** 이 3개 CLI는 소비자용 채팅 제품(claude.ai, ChatGPT,
Gemini 앱)이 아니라 **코딩 에이전트**다. 같은 모델이라도 코딩 에이전트 컨텍스트(시스템 프롬프트,
사용 가능 도구 목록, "당신은 코딩 어시스턴트다"류의 역할 설정)에서 나온 답변은 소비자 챗봇 답변과
다를 수 있다. 이 측정치는 소비자 대화형 AI에서의 노출도를 **완전히 대체하지 못하는 proxy(대리
지표)**다 — docs/metrics.md §7 측정 한계 참조.

## 1. Claude Code CLI

- 실행 파일: `claude`
- 참고: `claude --help`, `claude -p --help` (Anthropic 공식 문서)
- 어댑터: `backend/app/llm_clients/claude_code_cli_adapter.py`

### (a) 비대화형(headless) 실행 — `--bare`는 쓰지 않는다

```
claude -p "<프롬프트>" --output-format json --model <모델명> --tools WebSearch --allowedTools WebSearch
```

- `-p`(`--print`)로 비대화형 실행 — 답변을 stdout에 출력하고 즉시 종료한다.
- **`--bare`는 뺐다.** 실 CLI 파일럿(2026-07-13, Claude Code CLI v2.1.207)에서 `--bare` 모드가
  `claude setup-token`으로 발급한 `CLAUDE_CODE_OAUTH_TOKEN`을 인식하지 못하고 매번 "Not
  logged in · Please run /login"을 반환하는 것을 실측으로 확인했다(같은 토큰, 같은
  환경변수로 `--bare`만 빼면 정상 인증됨). 인증이 되지 않으면 애초에 측정 자체가 불가능하므로,
  `--bare`를 포기하고 인증을 택했다.
  - **잔여 컨텍스트 오염 위험**: `cli_common.run_cli()`가 cwd를 프로젝트와 무관한 전용 빈
    디렉터리(`CLI_WORKDIR`)로 강제하므로 **프로젝트 수준**(`CLAUDE.md`/`AGENTS.md`) 오염
    위험은 여전히 없다. 다만 `--bare` 없이는 **사용자 계정 수준**의 스킬/MCP 서버/메모리가
    로드될 수 있다는 잔여 위험이 남는다 — 이는 이 CLI 버전의 제약에 따른 받아들인 한계다
    (docs/metrics.md §7 측정 한계 참조).
- `--output-format json`으로 구조화된 응답을 받는다(기본값은 사람이 읽기용 텍스트라 파싱이
  불안정하다).

### (b) 웹 검색 도구 노출 — `--bare` 없이도 그대로 동작

`--tools WebSearch --allowedTools WebSearch`로 노출 도구를 WebSearch 하나로 제한하고 동시에
사전 승인한다(headless라 승인 프롬프트에 응답할 방법이 없어, 사전 승인하지 않으면 도구 사용
시도 자체가 멈춘다). 최종 명령:

```
claude -p "<프롬프트>" --model <모델명> --output-format json --tools WebSearch --allowedTools WebSearch
```

### (c) 응답 스키마

```json
{
  "type": "result",
  "subtype": "success",
  "is_error": false,
  "result": "<응답 텍스트>",
  "usage": { "input_tokens": 120, "output_tokens": 340 },
  "total_cost_usd": 0.0087
}
```

- `result`: 응답 텍스트 → `LLMResponse.text`.
- `is_error: true`면 `result`에 오류 메시지가 들어있다 — 어댑터는 이 경우 `LLMAdapterError`를
  던진다(재시도 대상 여부는 `cli_common.run_cli`가 종료 코드/stderr로 이미 분류했으므로, 여기서는
  "0으로 종료했지만 논리적으로 실패"한 경우만 잡는다).
- `usage.input_tokens`/`usage.output_tokens` → `LLMResponse.input_tokens`/`output_tokens`.
- `total_cost_usd` → `LLMResponse.cost_usd` (Claude Code CLI는 3개 CLI 중 유일하게 호출 단위
  실비용을 자기보고한다).
- **citation은 구조화된 필드로 오지 않는다** — `citations`는 항상 `[]`이고, 파싱 엔진의 본문 URL
  정규식 폴백(`app/services/citation_extraction.py`)이 유일한 추출 경로다.

### (d) `web_search_used` 판정의 한계

비-스트리밍 `--output-format json` 출력에는 "이번 호출에서 실제로 WebSearch 도구를 호출했는가"를
가리키는 필드가 없다. 그래서 어댑터는 `web_search_used = WEB_SEARCH_ENABLED`(고정 `True` 상수)를
반환한다 — 이는 "이 호출에서 WebSearch 도구가 허용되어 있었다"는 뜻이지 "모델이 실제로 검색했다"는
증명이 아니다. **알려진 한계로 기록한다.**

### (e) 인증

`claude setup-token`으로 발급한 장기 OAuth 토큰(`CLAUDE_CODE_OAUTH_TOKEN` 환경변수)을 쓴다 —
docs/operations.md §1 참조. Pro/Max/Team/Enterprise 등 구독 플랜의 좌석 rate limit을 공유한다.

## 2. Codex CLI

- 실행 파일: `codex`
- 참고: `codex exec --help` (OpenAI 공식 문서)
- 어댑터: `backend/app/llm_clients/codex_cli_adapter.py`

### (a) 비대화형 실행

```
codex exec -m <모델명> -s read-only --skip-git-repo-check -o <output_file> "<프롬프트>"
```

- `exec` 서브커맨드가 비대화형 단발 실행이다(대화형 TUI가 기본 동작이라 반드시 붙여야 한다).
- `-m`으로 모델을 고정한다.
- `-s read-only`(승인 모드): 파일 수정/셸 명령 실행에 대한 승인을 요구하지 않고 읽기 전용으로
  제한한다.
- **`--skip-git-repo-check`는 필수다.** `CLI_WORKDIR`는 의도적으로 git 저장소가 아닌 전용 빈
  디렉터리인데, Codex CLI는 기본적으로 git 저장소 밖에서 실행되면
  `Not inside a trusted directory and --skip-git-repo-check was not specified`라며 즉시
  실행을 거부한다. 이 플래그가 없으면 codex-cli 채널은 배치에서 매번 100% 실패한다.
- **`--search`는 쓰지 않는다.** Codex CLI v0.144.1에서 이 플래그를 넘기면
  `error: unexpected argument '--search' found`로 즉시 거부되는 것을 확인했다. 같은 버전에서
  `--search` 없이 실행해도 실제로 웹 검색을 수행하는 것도 함께 확인했다 — 이 버전부터는 웹
  검색이 기본으로 켜져 있는 것으로 보인다. 버전이 다시 바뀌면 `codex exec --help`로 플래그를
  재확인해야 한다.

### (b) 텍스트 추출 — `-o`가 JSON 이벤트 스트림 파싱보다 안전한 이유

Codex CLI의 `--json` 옵션은 실행 중 발생하는 이벤트를 줄 단위 JSON(JSONL)으로 흘려보낸다 — 최종
답변만 뽑으려면 이벤트 타입을 구분하는 파싱 로직이 필요하고, 이벤트 스키마가 버전마다 바뀔 위험이
크다. 반면 `-o/--output-last-message <path>`는 **최종 응답 텍스트만 지정한 파일에 그대로
써준다.** 어댑터는 매 호출마다 OS 임시 디렉터리에 고유 파일명(`geo-tracker-codex-<uuid>.txt`)을
만들어 `-o`로 넘기고, 호출이 끝나면 파일을 읽어 `LLMResponse.text`에 담은 뒤 `finally` 블록에서
즉시 삭제한다(동시 실행 중인 다른 codex 호출과 파일이 겹치지 않게 하기 위해 매번 새 이름을 쓴다).

### (c) 토큰 사용량 / 비용 — 항상 `None`

`-o` 경로로는 토큰 수를 받을 수 없다. `input_tokens`/`output_tokens`/`cost_usd`는 항상 `None`이다.

### (d) `web_search_used` 판정의 한계

`-o`로 받는 최종 텍스트만으로는 실제로 검색 도구가 호출됐는지 확인할 수 없다. `--search` 플래그
자체가 없어졌으므로 "플래그가 지정되어 있었다"는 근거도 없다 — 이 버전은 검색이 항상 켜져 있는
것으로 보이므로 `web_search_used = WEB_SEARCH_ENABLED = True` 상수를 그대로 유지한다.

### (e) 인증

`codex login`(device-auth 방식: 터미널에 코드가 표시되고 브라우저에서 승인) 흐름으로 로컬에
저장된 자격증명을 재사용한다 — docs/operations.md §2 참조.

## 3. Gemini CLI

- 실행 파일: `gemini`
- 참고: `gemini --help` (Google 공식 문서)
- 어댑터: `backend/app/llm_clients/gemini_cli_adapter.py`

### (a) 비대화형 실행

```
gemini -p "<프롬프트>" -m <모델명> --output-format json
```

### (b) 웹 검색 — 세 CLI 중 유일하게 별도 활성화 플래그가 없다

Gemini CLI는 `google_web_search` 도구를 **기본으로 항상 노출**한다. 모델이 필요하다고 판단하면
알아서 호출한다.

### (c) 응답 스키마

```json
{
  "response": "<응답 텍스트>",
  "stats": {
    "models": { "gemini-2.5-pro": { "tokens": { "prompt": 50, "candidates": 200 } } },
    "tools": { "google_web_search": { "count": 1 } }
  }
}
```

- `response` → `LLMResponse.text`.
- `error` 필드가 있으면 실패로 간주해 `LLMAdapterError`를 던진다.
- `stats.models.<model>.tokens.{prompt,candidates}` → `input_tokens`/`output_tokens`.
- `stats.tools.google_web_search.count` → **세 CLI 중 유일하게 "이번 호출에서 실제로 검색
  도구가 몇 번 호출됐는지"를 신뢰성 있게 알 수 있는 필드다.**
- 구조화된 citation 필드는 없다 — 본문 URL 정규식 폴백을 쓴다(다른 두 CLI와 동일).

### (d) 토큰/비용

`cost_usd`는 항상 `None`이다(구독 좌석이라 호출당 실비용 개념 자체가 없다).

### (e) 인증

최초 1회 브라우저에서 OAuth 로그인하면 자격증명이 로컬에 캐시되고, 이후 헤드리스 실행에서는
그 캐시를 재사용한다 — docs/operations.md §3 참조. **Ubuntu 서버(GUI 없음)에서 최초 로그인이
실제로 되는지는 미검증 — Phase 8에서 최초 확인 필수(§7 참조).**

## 4. 세 CLI의 웹 검색 활성화/판정 방식 비교

| | Claude Code CLI | Codex CLI | Gemini CLI |
|---|---|---|---|
| 기본 상태 | `--bare`에서 기본 off | 기본 on(v0.144.1 — 과거엔 `--search` 필요했으나 플래그 자체가 제거됨) | 기본 on (플래그 불필요) |
| 활성화 방법 | `--tools WebSearch --allowedTools WebSearch` | (없음 — 항상 사용 가능) | (없음 — 항상 사용 가능) |
| 실제 호출 여부 확인 | 불가 (근사치만) | 불가 (근사치만) | **가능** (`stats.tools.google_web_search.count`) |
| `web_search_used` 신뢰도 | 낮음 | 낮음 | 높음 (필드 있을 때) |

## 5. 인증/사용량 한도 실패 분류

`backend/app/llm_clients/cli_common.py`가 stdout+stderr 텍스트를 패턴 매칭해 세 갈래로 분류한다.

- **인증 실패**(`not logged in`, `unauthorized`, `please run` 등) → `MissingAPIKeyError`, 재시도
  하지 않는다.
- **사용량 한도**(`usage limit`, `rate limit`, `429`, `quota` 등, Codex의 실측 문구
  "You've hit your usage limit" 포함) → `CLIRateLimitError`, `retry_with_backoff`의
  `long_delay_exceptions`에 등록되어 훨씬 긴 간격으로 재시도한다.
- **그 외 비정상 종료/타임아웃** → `CLIProcessError`/`CLITimeoutError`, 일반 간격으로 재시도한다.

## 6. 비용/사용량은 호출 수 기준이다

토큰 단가 기반 비용 계산은 구독 좌석 CLI에는 적용되지 않는다 — API 호출당 과금이 아니라 매달
고정 요금으로 좌석을 쓰기 때문이다.

- 사전 배치 추정(`backend/app/services/cost_estimate.py`)은 "예상 호출 수"만 계산한다(달러
  추정 없음) — `MAX_CALLS_PER_BATCH` 가드의 판단 근거로만 쓰인다.
- 사후 배치 리포트(`batch_runner.get_batch_status()`의 `total_cost_usd`)는 각 어댑터가
  자기보고한 `cost_usd`의 합이다 — Claude Code CLI만 실질적으로 0이 아닌 값을 채운다.
  Codex/Gemini CLI 몫은 항상 0으로 잡힌다(개별 `cost_usd`가 `None`이라 합계에서 제외됨).

## 7. Ubuntu 실행 방식

이 프로젝트는 Ubuntu 서버에 배포한다(참고 프로젝트는 Docker/WSL 없는 한글 Windows 환경 기준이라
아래 내용이 완전히 새로 작성됐다 — 옛 §7의 Windows 전용 내용은 더 이상 적용되지 않는다).

| | Claude Code CLI | Codex CLI | Gemini CLI |
|---|---|---|---|
| Linux 네이티브 지원 | 지원 | 지원 | 지원(순수 Node.js CLI) |
| 설치 명령 | `curl -fsSL https://claude.ai/install.sh \| bash` | `npm install -g @openai/codex` (Node.js 22+) | `npm install -g @google/gemini-cli` (Node.js 18+, 22 LTS 권장) |
| 설치 산출물 | 네이티브 바이너리(보통 `~/.local/bin/claude`) | npm 전역 설치 시 `/usr/local/bin` 심볼릭 링크(시스템 전역 Node) | 위와 동일 |

### 7.1 npm `.cmd` 셸 스크립트 우회 — Ubuntu에서는 불필요

참고 프로젝트(Windows)는 npm으로 설치한 CLI가 `.cmd` 셸 스크립트가 되어 `asyncio.create_
subprocess_exec()`가 직접 실행하지 못하는 문제가 있었고, `cli_common.py`의
`_adapt_for_windows()`(`cmd.exe /c`로 감싸는 우회)로 해결했다. **Ubuntu에서는 npm 전역 설치가
`/usr/local/bin`에 실행 가능한 셸 스크립트(shebang `#!/usr/bin/env node`)를 심볼릭 링크로
만들고, `subprocess.Popen(["codex", ...])`이 이를 바로 실행할 수 있다** — 이 우회 코드
자체를 이식하지 않았다(`app/llm_clients/cli_common.py` 참조). **다만 이 사실은 반드시 실제
Ubuntu 배포 서버에서 재확인해야 한다**(Phase 3/8 완료 기준 — 가정만으로 넘어가지 않는다).

### 7.2 서브프로세스 타임아웃 시 프로세스 그룹 종료

`subprocess.Popen(start_new_session=True, ...)`으로 새 세션(POSIX: `setsid`)을 만들어 띄우고,
타임아웃 시 `os.killpg(os.getpgid(pid), SIGKILL)`로 프로세스 그룹 전체를 죽인다 — CLI가 내부적으로
띄운 Node 자식 프로세스까지 정리하기 위해 필수다(단순 `process.kill()`만 하면 좀비 프로세스가
남을 수 있다). `os.killpg`/`os.getpgid`는 POSIX 전용이라 이 경로는 Ubuntu에서만 완전하게
동작한다 — 개발이 Windows에서 이루어질 경우 `process.kill()` 폴백이 대신 동작하지만, 그 경로는
자식 프로세스를 정리하지 못하므로 **운영 서버(Ubuntu)에서는 항상 `os.killpg` 경로를 타는지
확인**해야 한다(`ps`로 타임아웃 재현 후 자식 프로세스가 안 남는지 확인 — Phase 3/8 완료 기준).

### 7.3 인코딩

Ubuntu 환경은 기본 로케일이 UTF-8인 경우가 대부분이라 참고 프로젝트가 겪은 cp949 콘솔 인코딩
문제 자체가 발생하지 않는다. 그래도 `cli_common.py`의 `run_cli()`는 그대로 stdout/stderr를
바이트로 받아 `decode("utf-8", errors="replace")`로 직접 디코딩하는 방어 로직을 유지한다 —
서버 로케일 설정과 무관하게 항상 올바르게 읽히도록 하기 위해서다.

### 7.4 `uvicorn --reload` 문제는 해당 없음

참고 프로젝트(FastAPI+Windows)는 `uvicorn --reload`가 Windows에서 `SelectorEventLoop`를
강제해 `asyncio.create_subprocess_exec()`가 100% `NotImplementedError`로 실패하는 문제가 있었다.
이 프로젝트는 Flask(WSGI, 동기)+Gunicorn이고 CLI 실행도 `subprocess.Popen`(asyncio 자체를 안
씀)이라 이 문제 자체가 성립하지 않는다 — Flask 개발 서버(`flask run`)의 `--debug`/자동 리로드
기능도 별도 프로세스(worker 데몬)와 무관하므로 안전하게 켤 수 있다.

### 7.5 CLI 로그인(OAuth) — 헤드리스 서버에서 미검증

"다른 기기 브라우저로 URL을 열고 인증 코드를 붙여넣는" 방식은 로컬 브라우저 없이도 동작하는 게
원칙이지만, **Ubuntu 서버(GUI 없음)에서 세 CLI 모두 실제로 이 플로우가 되는지는 아직 확인되지
않았다** — Phase 8(실 CLI 파일럿)에서 최초 확인이 필수다. 안 되는 CLI가 있다면 로컬 PC에서
로그인한 뒤 자격증명 파일(`~/.claude/`, `~/.codex/`, `~/.gemini/` 등)을 서버로 안전하게 복사하는
대안을 검토한다(docs/operations.md에 절차 추가 예정 — 아직 실측 전).

## 8. 변경 이력

| 날짜 | 변경 내용 |
|---|---|
| 2026-07-09 | 참고 프로젝트(20260709): SDK 4개 프로바이더 최초 조사 (docs/llm_providers.md) |
| 2026-07-10 | 참고 프로젝트 STEP 6: CLI 3종 조사, 이 문서 최초 작성 |
| 2026-07-10 | 참고 프로젝트 STEP 7: Windows 실행 방식 조사(WSL 불필요 확인, npm .cmd 셸 실행 문제와 해결) |
| 2026-07-13 | 참고 프로젝트: 실 CLI 파일럿에서 §2(a) `--skip-git-repo-check` 누락 버그, §7.3 `uvicorn --reload` 문제, §2 `--search` 플래그 제거, §1(a) `--bare` 인증 문제를 각각 발견/반영 |
| 2026-07-15 | Flask+PostgreSQL+Ubuntu 재개발: 옛 §7(Windows 실행 방식)을 새 §7(Ubuntu 실행 방식)로 전면 교체 — npm 우회 불필요, 프로세스 그룹 kill 필수, uvicorn 문제 해당 없음, 헤드리스 로그인 미검증 항목 명시 |
