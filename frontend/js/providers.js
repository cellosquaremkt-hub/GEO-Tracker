// 측정 채널(LLM 프로바이더) 표시 이름/색상 매핑.
//
// STEP 6부터 활성 측정 채널은 Claude Code CLI / Codex CLI / Gemini CLI 3종이다(구독 좌석 기반
// 코딩 에이전트 CLI). 과거 SDK 기반 채널(ChatGPT/Gemini/Perplexity/Claude)은 llm_provider.
// is_active=false로 DB에 남아있을 뿐 더 이상 측정하지 않는다 — 화면에 노출될 때는 항상 "(과거,
// 비활성)"임을 알 수 있게 표시한다(작업 지시 8, 9번). docs/llm_clis.md 참조.
const CURRENT_CHANNELS = {
  "claude-code-cli": { label: "Claude Code CLI", short: "Claude Code", color: "#d97757" },
  "codex-cli": { label: "Codex CLI", short: "Codex", color: "#10a37f" },
  "gemini-cli": { label: "Gemini CLI", short: "Gemini", color: "#4285f4" },
};

const LEGACY_CHANNELS = {
  ChatGPT: { label: "ChatGPT (과거 SDK, 비활성)", short: "ChatGPT", color: "#9aa4b1" },
  Gemini: { label: "Gemini (과거 SDK, 비활성)", short: "Gemini", color: "#9aa4b1" },
  Perplexity: { label: "Perplexity (과거 SDK, 비활성)", short: "Perplexity", color: "#9aa4b1" },
  Claude: { label: "Claude (과거 SDK, 비활성)", short: "Claude", color: "#9aa4b1" },
};

export function isCurrentChannel(name) {
  return name in CURRENT_CHANNELS;
}

export function providerDisplayName(name) {
  return CURRENT_CHANNELS[name]?.label || LEGACY_CHANNELS[name]?.short || name;
}

export function providerShortName(name) {
  return CURRENT_CHANNELS[name]?.short || LEGACY_CHANNELS[name]?.short || name;
}

export function providerColor(name) {
  return CURRENT_CHANNELS[name]?.color || LEGACY_CHANNELS[name]?.color || "#5f6f7a";
}
