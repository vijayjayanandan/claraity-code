/**
 * Production welcome screen shown when chat is empty.
 *
 * Sections:
 *   1. Hero — branding + tagline + connection status
 *   2. Capabilities — feature cards grid
 *   3. Quick prompts — categorized clickable chips
 *   4. Keyboard shortcuts — reference strip
 *   5. Architecture summary — collapsible for technical users
 */
import { useState } from "react";

interface WelcomeScreenProps {
  onSendPrompt: (prompt: string) => void;
  connected?: boolean;
  modelName?: string;
  workingDirectory?: string;
}

/* ── Prompt categories ── */

interface PromptCategory {
  label: string;
  icon: string;
  prompts: { text: string; description: string }[];
}

const PROMPT_CATEGORIES: PromptCategory[] = [
  {
    label: "Understand",
    icon: "codicon-book",
    prompts: [
      { text: "Explain the architecture of this project", description: "Get a high-level overview" },
      { text: "What does this file do?", description: "Understand the current file" },
      { text: "Find all API endpoints in this codebase", description: "Map the public surface" },
    ],
  },
  {
    label: "Build",
    icon: "codicon-tools",
    prompts: [
      { text: "Add input validation to the user form", description: "Enhance existing code" },
      { text: "Write a REST endpoint for user registration", description: "Create new functionality" },
      { text: "Refactor this function to be more readable", description: "Improve code quality" },
    ],
  },
  {
    label: "Fix",
    icon: "codicon-debug-alt",
    prompts: [
      { text: "Find and fix bugs in this file", description: "Detect issues automatically" },
      { text: "Why is this test failing?", description: "Debug test failures" },
      { text: "Fix the TypeScript errors in this project", description: "Resolve compiler issues" },
    ],
  },
  {
    label: "Test",
    icon: "codicon-beaker",
    prompts: [
      { text: "Write unit tests for the User model", description: "Generate test coverage" },
      { text: "Add integration tests for the API layer", description: "Test system boundaries" },
      { text: "Review test coverage and suggest missing cases", description: "Audit test quality" },
    ],
  },
];

/* ── Feature cards ── */

interface Feature {
  icon: string;
  title: string;
  description: string;
}

const FEATURES: Feature[] = [
  {
    icon: "codicon-server",
    title: "Any LLM",
    description: "OpenAI, Claude, Ollama, DeepSeek, or any compatible API. Switch models mid-session.",
  },
  {
    icon: "codicon-shield",
    title: "Safe by Default",
    description: "4-layer safety gating reviews every file change. You approve before anything is written.",
  },
  {
    icon: "codicon-organization",
    title: "Sub-Agents",
    description: "Specialized code-reviewer, test-writer, and doc-writer agents with their own context.",
  },
  {
    icon: "codicon-tools",
    title: "25+ Tools",
    description: "File ops, search, web, LSP intelligence, and terminal execution with parallel processing.",
  },
  {
    icon: "codicon-history",
    title: "Session Memory",
    description: "Every conversation is persisted. Resume any session with full context and history.",
  },
  {
    icon: "codicon-diff",
    title: "Diff Preview",
    description: "Review proposed changes in VS Code's native diff editor. Undo any turn instantly.",
  },
];

/* ── Keyboard shortcuts ── */

const SHORTCUTS = [
  { keys: "Ctrl+Shift+L", action: "New chat" },
  { keys: "Ctrl+Shift+.", action: "Interrupt" },
  { keys: "Ctrl+Shift+H", action: "Session history" },
  { keys: "Ctrl+'", action: "Add selection to chat" },
  { keys: "@", action: "Mention a file" },
  { keys: "Shift+Enter", action: "New line" },
];

/* ── Architecture data ── */

const ARCHITECTURE_LINES = [
  { layer: "VS Code Extension", detail: "React webview + CodeLens + file badges + undo manager" },
  { layer: "Transport", detail: "stdio + TCP with JSON-RPC 2.0 protocol" },
  { layer: "Agent Core", detail: "Async streaming orchestrator with 4-layer tool gating" },
  { layer: "Tool System", detail: "25+ tools with parallel execution and configurable timeouts" },
  { layer: "Sub-Agents", detail: "Subprocess isolation with per-agent LLM and context window" },
  { layer: "LLM Backend", detail: "OpenAI / Anthropic / Ollama with retry, backoff, and caching" },
  { layer: "Memory", detail: "Working + episodic memory with token-budgeted context assembly" },
  { layer: "Persistence", detail: "JSONL ledger with in-memory projection and async writes" },
];

/* ── Component ── */

export function WelcomeScreen({
  onSendPrompt,
  connected,
  modelName,
  workingDirectory,
}: WelcomeScreenProps) {
  const [activeCategory, setActiveCategory] = useState(0);
  const [showArchitecture, setShowArchitecture] = useState(false);
  const [showShortcuts, setShowShortcuts] = useState(false);

  const projectName = workingDirectory
    ? workingDirectory.split(/[/\\]/).filter(Boolean).pop() || "project"
    : null;

  return (
    <div className="welcome-screen-v2">
      {/* ── Hero ── */}
      <div className="welcome-hero">
        <div className="welcome-logo">
          <i className="codicon codicon-sparkle welcome-logo-icon" />
        </div>
        <h1 className="welcome-heading">ClarAIty</h1>
        <p className="welcome-subtitle">AI Coding Agent</p>

        {/* Connection status pill */}
        <div className="welcome-status">
          {connected ? (
            <span className="status-pill connected">
              <i className="codicon codicon-check" />
              {modelName ? modelName : "Connected"}
              {projectName && (
                <span className="status-project"> in {projectName}</span>
              )}
            </span>
          ) : (
            <span className="status-pill disconnected">
              <i className="codicon codicon-circle-slash" />
              Not connected
              <span className="status-hint"> &mdash; configure LLM in settings</span>
            </span>
          )}
        </div>
      </div>

      {/* ── Feature cards ── */}
      <div className="welcome-section">
        <div className="welcome-features">
          {FEATURES.map((f) => (
            <div className="feature-card" key={f.title}>
              <div className="feature-icon-wrap">
                <i className={`codicon ${f.icon}`} />
              </div>
              <div className="feature-text">
                <span className="feature-title">{f.title}</span>
                <span className="feature-desc">{f.description}</span>
              </div>
            </div>
          ))}
        </div>
      </div>

      {/* ── Prompt categories ── */}
      <div className="welcome-section">
        <div className="welcome-section-header">Try asking</div>
        <div className="category-tabs">
          {PROMPT_CATEGORIES.map((cat, i) => (
            <button
              key={cat.label}
              className={`category-tab ${i === activeCategory ? "active" : ""}`}
              onClick={() => setActiveCategory(i)}
            >
              <i className={`codicon ${cat.icon}`} />
              {cat.label}
            </button>
          ))}
        </div>
        <div className="prompt-list">
          {PROMPT_CATEGORIES[activeCategory].prompts.map((p) => (
            <button
              key={p.text}
              className="prompt-card"
              onClick={() => onSendPrompt(p.text)}
            >
              <span className="prompt-text">{p.text}</span>
              <span className="prompt-desc">{p.description}</span>
              <i className="codicon codicon-arrow-right prompt-arrow" />
            </button>
          ))}
        </div>
      </div>

      {/* ── Collapsible sections ── */}
      <div className="welcome-section">
        {/* Keyboard shortcuts */}
        <button
          className="welcome-collapse-toggle"
          onClick={() => setShowShortcuts(!showShortcuts)}
        >
          <i className={`codicon codicon-chevron-${showShortcuts ? "down" : "right"}`} />
          Keyboard shortcuts
        </button>
        {showShortcuts && (
          <div className="shortcuts-grid">
            {SHORTCUTS.map((s) => (
              <div className="shortcut-row" key={s.keys}>
                <kbd className="shortcut-keys">{s.keys}</kbd>
                <span className="shortcut-action">{s.action}</span>
              </div>
            ))}
          </div>
        )}

        {/* Architecture */}
        <button
          className="welcome-collapse-toggle"
          onClick={() => setShowArchitecture(!showArchitecture)}
        >
          <i className={`codicon codicon-chevron-${showArchitecture ? "down" : "right"}`} />
          Architecture
        </button>
        {showArchitecture && (
          <div className="architecture-stack">
            {ARCHITECTURE_LINES.map((line, i) => (
              <div className="arch-layer" key={line.layer}>
                <div className="arch-connector">
                  <span className="arch-dot" />
                  {i < ARCHITECTURE_LINES.length - 1 && <span className="arch-line" />}
                </div>
                <div className="arch-content">
                  <span className="arch-name">{line.layer}</span>
                  <span className="arch-detail">{line.detail}</span>
                </div>
              </div>
            ))}
          </div>
        )}
      </div>

      {/* ── Footer ── */}
      <div className="welcome-footer">
        Type a message below to get started, or click a prompt above.
      </div>
    </div>
  );
}
