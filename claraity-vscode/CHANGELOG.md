# Changelog

All notable changes to the ClarAIty VS Code extension will be documented in this file.

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
- Sidebar sidebar enhancements for tool state display

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
