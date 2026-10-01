/**
 * Parity tests for utils/modelThinking.ts.
 *
 * Cases mirror tests/llm/test_adaptive_thinking_rules.py (Python) so the two
 * model-family checks cannot drift apart silently.
 */
import { describe, test, expect } from "vitest";
import {
  getThinkingMode,
  usesAdaptiveThinking,
  usesOpenAIReasoning,
} from "../utils/modelThinking";

describe("usesAdaptiveThinking (mirror of uses_adaptive_thinking)", () => {
  test.each([
    "claude-sonnet-5",
    "claude-fable-5",
    "claude-mythos-5",
    "claude-opus-5",
    "claude-opus-5-5",
    "claude-opus-4-7",
    "claude-opus-4-8",
    "vertex_ai/claude-sonnet-5",
    "anthropic.claude-opus-4-8",
    "Claude-Sonnet-5",
  ])("%s is adaptive", (m) => {
    expect(usesAdaptiveThinking(m)).toBe(true);
  });

  test.each([
    "claude-sonnet-4-5",
    "claude-sonnet-4-6",
    "claude-opus-4-6",
    "claude-haiku-4-5",
    "gpt-4o",
    "kimi-k2.5",
    "",
  ])("%s is not adaptive", (m) => {
    expect(usesAdaptiveThinking(m)).toBe(false);
  });

  test("null/undefined are not adaptive", () => {
    expect(usesAdaptiveThinking(null)).toBe(false);
    expect(usesAdaptiveThinking(undefined)).toBe(false);
  });
});

describe("usesOpenAIReasoning (mirror of uses_max_completion_tokens)", () => {
  test.each(["o1", "o3-mini", "o4-mini", "gpt-5", "gpt-5.1", "gpt-6.1-sol", "azure/gpt-6.1-sol", "gpt-10"])(
    "%s is a reasoning model",
    (m) => {
      expect(usesOpenAIReasoning(m)).toBe(true);
    },
  );

  test.each(["gpt-4o", "gpt-4.1", "solo1", "claude-opus-5-5", "kimi-k2.5", ""])(
    "%s is not a reasoning model",
    (m) => {
      expect(usesOpenAIReasoning(m)).toBe(false);
    },
  );
});

describe("getThinkingMode", () => {
  test("Claude adaptive -> claude_effort", () => {
    expect(getThinkingMode("claude-opus-5-5")).toBe("claude_effort");
  });
  test("OpenAI reasoning -> openai_effort", () => {
    expect(getThinkingMode("gpt-5.1")).toBe("openai_effort");
  });
  test("legacy Claude and others -> budget", () => {
    expect(getThinkingMode("claude-sonnet-4-6")).toBe("budget");
    expect(getThinkingMode("gpt-4o")).toBe("budget");
    expect(getThinkingMode("")).toBe("budget");
  });
});
