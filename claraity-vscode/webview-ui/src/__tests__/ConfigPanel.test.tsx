/**
 * ConfigPanel tests -- API key save flow.
 *
 * Covers:
 * - API key included in saveConfig payload when user types a new key
 * - API key NOT included when user doesn't change key (sentinel)
 * - Dirty check enables Save when only the API key changes
 * - Save button disabled when form is clean
 * - Backend switch + new key sends both in payload
 * - Search key follows the same pattern
 */
import { describe, test, expect, vi } from "vitest";
import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import React from "react";
import { ConfigPanel } from "../components/ConfigPanel";

// ---------------------------------------------------------------------------
// Helpers
// ---------------------------------------------------------------------------

/** Minimal configData that simulates a server config_loaded response. */
function makeConfigData(overrides: Record<string, unknown> = {}): Record<string, unknown> {
  return {
    backend_type: "openai",
    base_url: "https://api.openai.com/v1",
    has_api_key: true,
    model: "gpt-4o",
    temperature: 0.2,
    max_tokens: 16384,
    context_window: 131072,
    thinking_budget: null,
    web_search_provider: "tavily",
    has_search_key: false,
    subagent_models: {},
    prompt_enrichment: { model: "", system_prompt: "", default_system_prompt: "" },
    ...overrides,
  };
}

function renderConfigPanel(overrides: {
  configData?: Record<string, unknown> | null;
  postMessage?: ReturnType<typeof vi.fn>;
  configModels?: { models: string[]; error?: string } | null;
  configNotification?: { message: string; success: boolean } | null;
} = {}) {
  const postMessage = overrides.postMessage ?? vi.fn();
  const onBack = vi.fn();

  const result = render(
    <ConfigPanel
      postMessage={postMessage}
      onBack={onBack}
      configData={overrides.configData ?? makeConfigData()}
      configSubagentNames={[]}
      configModels={overrides.configModels ?? null}
      configNotification={overrides.configNotification ?? null}
    />,
  );

  return { postMessage, onBack, ...result };
}

/** Find the API key input (first password field). */
function getApiKeyInput(): HTMLInputElement {
  const inputs = screen.getAllByPlaceholderText("Enter new key to update");
  return inputs[0] as HTMLInputElement;
}

/** Find the search key input (second password field). */
function getSearchKeyInput(): HTMLInputElement {
  const inputs = screen.getAllByPlaceholderText("Enter new key to update");
  return inputs[1] as HTMLInputElement;
}

/** Find the Save button. */
function getSaveButton(): HTMLButtonElement {
  return screen.getByTitle("Save settings") as HTMLButtonElement;
}

/** Extract the saveConfig payload from postMessage mock calls. */
function findSavePayload(postMessage: ReturnType<typeof vi.fn>): Record<string, unknown> | undefined {
  const call = postMessage.mock.calls.find(
    (c: unknown[]) => (c[0] as Record<string, unknown>).type === "saveConfig",
  );
  if (!call) return undefined;
  return (call[0] as Record<string, unknown>).config as Record<string, unknown>;
}

// ---------------------------------------------------------------------------
// Tests
// ---------------------------------------------------------------------------

describe("ConfigPanel API key save flow", () => {
  test("typing a new API key and saving includes api_key in payload", async () => {
    const user = userEvent.setup();
    const { postMessage } = renderConfigPanel();

    // Focus the key field (clears sentinel), type new key
    const input = getApiKeyInput();
    await user.click(input);
    await user.type(input, "sk-ant-new-key-123");

    // Save should be enabled (dirty due to key change)
    expect(getSaveButton()).not.toBeDisabled();
    await user.click(getSaveButton());

    const config = findSavePayload(postMessage);
    expect(config).toBeDefined();
    expect(config!.api_key).toBe("sk-ant-new-key-123");
  });

  test("saving without changing API key does NOT include api_key in payload", async () => {
    const user = userEvent.setup();
    const { postMessage } = renderConfigPanel();

    // Change model to make the form dirty (without touching the key)
    const modelInput = screen.getByPlaceholderText("gpt-4o") as HTMLInputElement;
    await user.clear(modelInput);
    await user.type(modelInput, "gpt-4o-mini");

    expect(getSaveButton()).not.toBeDisabled();
    await user.click(getSaveButton());

    const config = findSavePayload(postMessage);
    expect(config).toBeDefined();
    expect(config!.api_key).toBeUndefined();
  });

  test("API key change alone enables Save button (dirty check)", async () => {
    const user = userEvent.setup();
    renderConfigPanel();

    // Initially Save is disabled (clean form)
    expect(getSaveButton()).toBeDisabled();

    // Type a new key
    const input = getApiKeyInput();
    await user.click(input);
    await user.type(input, "sk-ant-dirty-check");

    // Save should now be enabled
    expect(getSaveButton()).not.toBeDisabled();
  });

  test("focusing and blurring API key field without typing does NOT dirty the form", async () => {
    const user = userEvent.setup();
    renderConfigPanel();

    expect(getSaveButton()).toBeDisabled();

    // Focus (clears sentinel) then blur (restores sentinel)
    const input = getApiKeyInput();
    await user.click(input);
    await user.tab(); // blur

    expect(getSaveButton()).toBeDisabled();
  });

  test("switching backend and entering new API key includes both in payload", async () => {
    const user = userEvent.setup();
    const { postMessage } = renderConfigPanel();

    // Switch backend to anthropic
    const backendSelect = screen.getByDisplayValue("OpenAI-compatible") as HTMLSelectElement;
    await user.selectOptions(backendSelect, "anthropic");

    // Type new key
    const input = getApiKeyInput();
    await user.click(input);
    await user.type(input, "sk-ant-backend-switch");

    expect(getSaveButton()).not.toBeDisabled();
    await user.click(getSaveButton());

    const config = findSavePayload(postMessage);
    expect(config).toBeDefined();
    expect(config!.backend_type).toBe("anthropic");
    expect(config!.api_key).toBe("sk-ant-backend-switch");
  });

  test("search key change includes search_key in payload", async () => {
    const user = userEvent.setup();
    const { postMessage } = renderConfigPanel();

    const searchInput = getSearchKeyInput();
    await user.click(searchInput);
    await user.type(searchInput, "tvly-new-search-key");

    expect(getSaveButton()).not.toBeDisabled();
    await user.click(getSaveButton());

    const config = findSavePayload(postMessage);
    expect(config).toBeDefined();
    expect(config!.search_key).toBe("tvly-new-search-key");
  });
});
