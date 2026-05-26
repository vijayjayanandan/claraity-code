# ClarAIty Agent Memory

- [Task tools testing session](task-tools-testing.md) -- all task tool actions verified working on 2026-04-07; user testing new enhancements
- [User profile](user-profile.md) -- project owner/developer, prefers interactive demos, tests systematically
- [Communication style](user-communication-style.md) -- clear and concise responses only, no verbose explanations
- [Build and Publish Process](build-and-publish-process.md) -- Python binary (.venv-build + PyInstaller), webview (Vite), extension (esbuild), VSIX packaging, marketplace publish, GitHub push
- [run_command cancellation context](run-command-cancellation-context.md) -- VS Code Stop uses orphan fixer path (agent.py:1333), not CancelledError handlers; three distinct cancellation message paths; subprocess kill pattern
- [Director mode session 2026-04-26](director-mode-session-2026-04-26.md) -- full feature built; 2 bugs still pending (CSS missing, /director routing); parallel session clobbering lesson; director deadlock bug documented
- [No session redaction](no-session-redaction.md) -- secret redaction removed from writer.py; file permissions are the security boundary; do not re-add
- [Multi-root workspace](multi-root-workspace.md) -- multi-folder workspace + outside-workspace approval gate; `_workspace_roots: list[Path]`; gating handles security upstream
- [Skill system](skill-system.md) -- full skill architecture: directory-based, dual-directory SkillLoader, built-in skill-creator toolkit, preprocessing, slash commands, VS Code integration

- [Educational Presentation State](educational-presentation-state.md) -- Tracking progress for the Telus Health 14-chapter agent demo (Ch 1-10 complete, Ch 11-14 slides-only)
- [MCP SDK Integration Session 2026-05-18](mcp-sdk-integration-session.md) -- SdkTransport, OAuth, token storage, code review fixes, useSdk=true default; Rovo needs url/transport not command/mcp-remote
- [Presentation File Architecture](presentation-file-architecture.md) -- How index.html, slides.js, glossary.js, engine.js interact; load order, [[Term]] syntax, glossary popup wiring, diagram system, chapter tracking
- [OpenAI Native Backend Session 2026-05-24](openai-native-backend-session.md) -- capability-map fail-safe pattern, .create() not .stream(), reasoning_effort kwarg shapes, API key hot-swap fix, respx smoke test pattern