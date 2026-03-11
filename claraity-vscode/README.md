# ClarAIty - AI Coding Agent for VS Code

ClarAIty brings a powerful AI coding agent directly into your editor. Chat with an AI that can read, write, and refactor your code — with full approval controls so you stay in charge.

## Features

### Chat with Your Codebase
Open the ClarAIty sidebar and describe what you need. The agent reads your files, proposes changes, and executes commands — all with your approval.

- **Streaming responses** with real-time markdown rendering and syntax highlighting
- **Tool call visibility** — see every file read, edit, and command the agent executes
- **Approval controls** — review and approve/reject file changes before they're applied
- **Inline diffs** — view proposed changes as VS Code diffs before accepting

### Editor Integration

- **Context menu** — right-click selected code to explain, fix, refactor, or send to chat
- **@file mentions** — type `@` in the chat input to reference files by name
- **Image/screenshot support** — paste or drag images into chat for visual context
- **File decorations** — files modified by the agent are marked in the explorer
- **CodeLens** — inline accept/reject buttons appear on files with pending changes
- **Terminal echo** — agent commands are displayed in a dedicated terminal

### Workspace Awareness
ClarAIty automatically detects your project type (language, framework, test runner, package manager, build tool) and provides this context to the agent for better suggestions.

Supported: TypeScript, JavaScript, Python, Rust, Go, Java | React, Next.js, Vue, Angular, Django, FastAPI, Flask, Express, and more.

### Session Management

- **Session history** — browse and resume previous conversations
- **Undo/rollback** — revert all file changes from an agent turn with one click
- **Cost tracking** — see token usage and estimated cost per response

### Keyboard Shortcuts

| Action | Windows/Linux | Mac |
|--------|---------------|-----|
| New Chat | `Ctrl+Shift+L` | `Cmd+Shift+L` |
| Interrupt Agent | `Ctrl+Shift+.` | `Cmd+Shift+.` |
| Session History | `Ctrl+Shift+H` | `Cmd+Shift+H` |
| Add Selection to Chat | `Ctrl+'` | `Cmd+'` |

## Requirements

- The ClarAIty Python agent server (`claraity-code` package) must be installed
- Python 3.10 or later
- An API key for a supported LLM provider (OpenAI, Anthropic, or OpenAI-compatible)

The extension auto-detects your Python environment and starts the server automatically. If the agent package is not installed, it will prompt you to install it.

## Extension Settings

| Setting | Default | Description |
|---------|---------|-------------|
| `claraity.pythonPath` | `python` | Path to Python interpreter |
| `claraity.serverAutoStart` | `true` | Auto-start the Python agent server |
| `claraity.serverUrl` | `ws://localhost:9120/ws` | WebSocket URL (manual mode) |
| `claraity.autoConnect` | `true` | Connect on activation (manual mode) |
| `claraity.autoInstallAgent` | `true` | Prompt to install agent package |
| `claraity.devMode` | `auto` | Server launch mode (`auto`, `always`, `never`) |

## How It Works

1. **Extension activates** when you open the ClarAIty sidebar
2. **Server starts** — the Python agent server launches in the background
3. **WebSocket connects** — real-time bidirectional communication
4. **You chat** — describe tasks, the agent proposes and executes changes
5. **You approve** — review diffs and approve/reject each file modification

## Security

- All rendered markdown is sanitized with [DOMPurify](https://github.com/cure53/DOMPurify) to prevent XSS
- Content Security Policy restricts webview capabilities
- File changes require explicit approval (unless auto-approve is enabled)
- No data is sent to external services — communication stays between VS Code and your local server

## Known Issues

- The extension requires a running Python server; if the server crashes, reconnect via the status bar
- Large files may take longer to process through the agent

## Release Notes

See [CHANGELOG](CHANGELOG.md) for version history.
