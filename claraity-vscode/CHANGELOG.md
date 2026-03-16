# Changelog

All notable changes to the ClarAIty VS Code extension will be documented in this file.

## [0.2.2] - 2026-03-16

### Fixed
- **Extension activation crash on marketplace installs** — `ws` dependency was excluded from VSIX package, causing `Cannot find module 'ws'` on activation. Switched from `tsc` to esbuild bundling to inline all dependencies into a single `out/extension.js`
- **Blank webview on first load** — codicon font blocked by Content Security Policy (`font-src` missing `data:` for base64-embedded fonts)
- **Server crash on missing API key** — agent binary now starts gracefully without an API key, allowing users to configure via the Settings panel instead of crashing at startup
- **Bloated VSIX** — excluded `.clarity/`, playwright artifacts, and esbuild config from package; cleaned up duplicate PyInstaller build in `bin/`

### Added
- esbuild bundler for production builds (replaces raw `tsc` output)
- Premium UI enhancements: streaming cursor, thinking shimmer animation, welcome screen with prompt chips, context bar color gradient (green/amber/red), scroll-to-bottom pill during streaming, message hover copy button
- Welcome screen shown on empty chat with feature cards, categorized prompt suggestions, keyboard shortcuts reference, and architecture overview

### Changed
- Updated marketplace readme with current feature set, architecture diagram, and simplified getting started guide
- VSIX size reduced from 115MB to ~31MB (removed duplicate binary, excluded dev artifacts)

## [0.2.0] - 2026-03-15

### Added
- **React webview UI** — full chat interface built with React, replacing inline HTML
  - 22 components: ChatHistory, MessageBubble, ToolCard, SubagentCard, CodeBlock, ThinkingBlock, InputBox, ConfigPanel, SessionPanel, and more
  - State management via useReducer with 1200+ line reducer
  - 314 unit tests (vitest + testing-library)
- **stdio transport** — JSON-RPC 2.0 over stdin/stdout as alternative to WebSocket, with TCP data channel for streaming events
- **Bundled binary** — PyInstaller-built `claraity-server.exe` included in `bin/`, eliminating the need for Python installation
- **Session scanner** — session history listing without loading full JSONL files
- **Hot-swap LLM config** — change model, temperature, and other settings without restarting the server
- **Subagent approval promotion** — subagent approval requests surfaced to the main conversation level
- **Jira integration panel** — connect to Jira Cloud for issue management from the sidebar

### Changed
- Connection mode configurable: `websocket` (default) or `stdio` (experimental)
- Webview mode configurable: `auto`, `react`, or `inline` fallback

## [0.1.2] - 2026-03-11

### Changed
- Reduced VSIX size significantly by excluding webview-ui build artifacts and node_modules from package

## [0.1.1] - 2026-03-11

### Added
- Background task monitoring UI with real-time status and toast notifications
- Granular auto-approve panel with per-category toggles (Edit files, Run commands, Browser tools)
- Plan/Act mode toggle replacing the previous 3-mode dropdown
- Enhanced tool card and subagent card rendering in sidebar
- PowerShell command compatibility layer for Windows users

### Changed
- Improved tool card rendering with better status indicators
- Sidebar enhancements for tool state display

## [0.1.0] - 2025-03-08

### Added
- Sidebar chat with streaming markdown rendering and syntax highlighting
- Tool call cards with real-time status (pending, running, success, error)
- File change approval with inline diff viewer
- CodeLens provider for inline accept/reject on pending changes
- File decoration provider marking agent-modified files
- Terminal integration echoing agent commands
- @file context mentions with fuzzy file search
- Image/screenshot support via paste and drag-and-drop
- Session history browser with resume capability
- Undo/rollback for reverting agent file changes per turn
- Workspace detection for project context enrichment
- Editor context menu (Explain, Fix, Refactor, Add to Chat)
- Keyboard shortcuts for common actions
- Cost and token tracking per response
- Auto-approve panel with per-category toggles (edit, execute, browser)
- Plan/Act mode toggle
- Server auto-start with Python environment detection
- Structured logging to Output Channel
- DOMPurify HTML sanitization for XSS prevention
- Content Security Policy for webview security
