/**
 * Model-family detection for the Thinking control in Settings.
 *
 * MIRROR of src/llm/model_config.py (uses_adaptive_thinking,
 * uses_max_completion_tokens, CLAUDE_EFFORT_LEVELS, OPENAI_EFFORT_LEVELS).
 * Keep both in sync -- modelThinking.test.ts uses the same cases as
 * tests/llm/test_adaptive_thinking_rules.py.
 */

/** Which thinking control a model gets. */
export type ThinkingMode = "claude_effort" | "openai_effort" | "budget";

const ADAPTIVE_THINKING_MARKERS = [
  "claude-fable-5",
  "claude-mythos-5",
  "claude-sonnet-5",
  "claude-opus-5",
  "claude-opus-4-7",
  "claude-opus-4-8",
];

const MODERN_OPENAI_RE = /(?:^|[/:.])(?:o[1-9](?:-|$)|gpt-(?:[5-9]|\d{2,}))/;

export const CLAUDE_EFFORT_OPTIONS: Array<{ value: string; label: string }> = [
  { value: "low", label: "Low" },
  { value: "medium", label: "Medium" },
  { value: "high", label: "High" },
  { value: "xhigh", label: "Extra high" },
  { value: "max", label: "Max" },
];

export const OPENAI_EFFORT_OPTIONS: Array<{ value: string; label: string }> = [
  { value: "low", label: "Low" },
  { value: "medium", label: "Medium" },
  { value: "high", label: "High" },
];

export const ALL_EFFORT_LEVELS = CLAUDE_EFFORT_OPTIONS.map((o) => o.value);

/** Shown and sent when nothing is saved -- Anthropic's own default for Opus 5.5. */
export const CLAUDE_DEFAULT_EFFORT = "medium";

export function usesAdaptiveThinking(model: string | null | undefined): boolean {
  const name = (model || "").toLowerCase();
  return ADAPTIVE_THINKING_MARKERS.some((m) => name.includes(m));
}

export function usesOpenAIReasoning(model: string | null | undefined): boolean {
  return MODERN_OPENAI_RE.test((model || "").toLowerCase());
}

export function getThinkingMode(model: string | null | undefined): ThinkingMode {
  if (usesAdaptiveThinking(model)) return "claude_effort";
  if (usesOpenAIReasoning(model)) return "openai_effort";
  return "budget";
}
