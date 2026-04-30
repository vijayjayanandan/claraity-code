# ClarAIty Agent Memory

- [Task tools testing session](task-tools-testing.md) -- all task tool actions verified working on 2026-04-07; user testing new enhancements
- [User profile](user-profile.md) -- project owner/developer, prefers interactive demos, tests systematically
- [Communication style](user-communication-style.md) -- clear and concise responses only, no verbose explanations
- [Build and Publish Process](build-and-publish-process.md) -- Python binary (.venv-build + PyInstaller), webview (Vite), extension (esbuild), VSIX packaging, marketplace publish, GitHub push
- [run_command cancellation context](run-command-cancellation-context.md) -- VS Code Stop uses orphan fixer path (agent.py:1333), not CancelledError handlers; three distinct cancellation message paths; subprocess kill pattern
- [Director mode session 2026-04-26](director-mode-session-2026-04-26.md) -- full feature built; 2 bugs still pending (CSS missing, /director routing); parallel session clobbering lesson; director deadlock bug documented
- [No session redaction](no-session-redaction.md) -- secret redaction removed from writer.py; file permissions are the security boundary; do not re-add
