# ClarAIty - AI Coding Agent for VS Code

An intelligent coding assistant that reads your code, executes tools, delegates to specialized sub-agents, and asks before making changes — **powered by any LLM you choose**.

ClarAIty brings a full-featured AI coding agent directly into your editor. Not just a chat window — deep VS Code integration with CodeLens, file decorations, inline diffs, turn-level undo, and a 4-layer safety system that ensures you stay in control.

## Key Capabilities

### Any LLM, Your Choice

Use OpenAI, Anthropic Claude, Ollama (local), DeepSeek, Kimi, or any OpenAI-compatible API. Switch models mid-session without restarting. Configure per-subagent model overrides for cost optimization.

### Human-in-the-Loop Safety

4-layer safety gating ensures the agent asks before making changes:

- **Repeat detection** — blocks identical failing operations
- **Plan mode** — read-only exploration before execution
- **Director workflow** — phased execution with checkpoints
- **Approval system** — review diffs before file writes

### Specialized Sub-Agents

Delegate tasks to purpose-built sub-agents, each with their own context window and optimized prompts:

- **code-reviewer** — finds bugs, security issues, and improvements
- **test-writer** — generates comprehensive test suites
- **doc-writer** — creates documentation from code
- **explore** — researches codebases and answers questions

### 25+ Built-in Tools

Parallel execution, intelligent error recovery, and configurable timeouts:

- Read, write, and edit files with diff preview
- Run commands in an integrated terminal
- Search code with grep and glob patterns
- Web search and fetch for documentation
- LSP-powered code intelligence (outlines, symbols)

### Session Memory

Every conversation is persisted and resumable. The agent remembers context across turns, compacts old messages intelligently, and maintains working memory of your session history. Browse, resume, or start fresh at any time.

### Deep VS Code Integration

- **CodeLens** — inline Accept / Reject / View Diff buttons on modified files
- **File decorations** — see which files the agent modified in the explorer
- **Diff editor** — full VS Code diff view for proposed changes
- **Turn undo** — revert all changes from any agent turn with one click
- **Context menu** — right-click selected code to explain, fix, refactor, or send to chat
- **@file mentions** — type `@` in the chat input to reference files by name
- **Image support** — paste or drag images into chat for visual context
- **Terminal echo** — agent commands are displayed in a dedicated terminal
- **Cost tracking** — see token usage and estimated cost per response

## Getting Started

### 1. Install

Install ClarAIty from the VS Code Marketplace. The extension bundles a self-contained agent binary — no Python installation required.

### 2. Configure Your LLM

Click the gear icon in the sidebar toolbar to open Settings. Enter your API base URL, API key, and select a model. Supports OpenAI, Anthropic, Ollama, Azure OpenAI, Groq, Together.ai, DeepSeek, Kimi, and any OpenAI-compatible endpoint.

### 3. Start Chatting

Type a message in the chat input. The agent will analyze your workspace, read relevant files, and respond with context-aware assistance.

**Try these first messages:**
- "Explain the architecture of this project"
- "Find and fix bugs in src/auth.ts"
- "Write unit tests for the User model"
- "Refactor the database layer to use connection pooling"

### 4. Review and Approve

When the agent proposes file changes, you'll see a diff preview. Click **Accept** to apply or **Reject** to decline. Use the auto-approve toggle for trusted operations like file reads and searches.

## Workspace Awareness

ClarAIty automatically detects your project type (language, framework, test runner, package manager, build tool) and provides this context to the agent for better suggestions.

Supported: TypeScript, JavaScript, Python, Rust, Go, Java | React, Next.js, Vue, Angular, Django, FastAPI, Flask, Express, and more.

## Keyboard Shortcuts

| Action | Windows/Linux | Mac |
|--------|---------------|-----|
| New Chat | `Ctrl+Shift+L` | `Cmd+Shift+L` |
| Interrupt Agent | `Ctrl+Shift+.` | `Cmd+Shift+.` |
| Session History | `Ctrl+Shift+H` | `Cmd+Shift+H` |
| Add Selection to Chat | `Ctrl+'` | `Cmd+'` |
| New Line in Message | `Shift+Enter` | `Shift+Enter` |

## Extension Settings

| Setting | Default | Description |
|---------|---------|-------------|
| `claraity.connectionMode` | `websocket` | Transport: `websocket` (HTTP+WS) or `stdio` (stdin/stdout pipes) |
| `claraity.pythonPath` | `python` | Path to Python interpreter (when not using bundled binary) |
| `claraity.serverAutoStart` | `true` | Auto-start the agent server on activation |
| `claraity.serverUrl` | `ws://localhost:9120/ws` | WebSocket URL (websocket mode) |
| `claraity.autoConnect` | `true` | Connect on activation (websocket mode) |
| `claraity.autoInstallAgent` | `true` | Prompt to install agent package if not found |
| `claraity.devMode` | `auto` | Server launch mode: `auto`, `always` source, `never` source |
| `claraity.webviewMode` | `auto` | UI mode: `auto`, `react`, or `inline` fallback |

## Security

- All rendered markdown is sanitized with DOMPurify to prevent XSS
- Content Security Policy restricts webview capabilities
- File changes require explicit approval (unless auto-approve is enabled)
- Communication stays between VS Code and your local agent — no data sent to external services beyond your configured LLM provider
- SSRF protection validates outbound URLs for model listing

## Release Notes

See [CHANGELOG](CHANGELOG.md) for version history.
