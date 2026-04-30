---
name: Multi-Root Workspace & Outside-Workspace Security Gate
description: VS Code multi-folder workspace support with approval-based security for outside-workspace file access
type: project
---

## Multi-Root Workspace Support (2026-04-30)

### What was built:
1. **Multi-root workspace** -- all VS Code workspace folders are accessible, not just the first one
2. **Outside-workspace approval gate** -- accessing files outside workspace always prompts user, even if auto-approve is on

### Security model:
- Inside workspace + auto-approve on = allowed silently
- Inside workspace + auto-approve off = normal approval prompt
- Outside workspace (any mode) = ALWAYS prompt (safety floor, `safety_reason` blocks "allow all" bypass)

### Key architecture:
- `FileOperationTool._workspace_roots: list[Path]` -- class-level, first entry is primary
- `ToolGatingService.check_outside_workspace()` -- gate #4 in evaluate(), after command safety
- All file tools pass `allow_outside_workspace=True` -- gating handles security upstream, not tools
- `validate_path_security()` accepts `Path | list[Path]`
- Search tools hint about other folders when using default path
- Context builder injects workspace folders into system prompt
- Mid-session updates via `workspace_folders_changed` stdin command

### Files touched: 16 source + 7 test files, 28 new tests
### Code review: APPROVE (4.8/5), no critical issues
