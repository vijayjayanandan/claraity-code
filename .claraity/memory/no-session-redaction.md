---
name: No secret redaction in session persistence
description: Secret redaction removed from writer.py. File permissions are the security boundary. Do not re-add redaction.
type: feedback
---

Session persistence must NOT redact secrets via regex. Redaction was removed on 2026-04-28.

**Why:** Regex-based `redact_secrets()`/`redact_dict()` operated on serialized JSON strings (tool_call `arguments` field), corrupting JSON structure and making sessions permanently unloadable. ClarAIty is a local dev tool -- file permissions (secure_file, 600) are the appropriate security boundary, matching industry standard (Copilot, Cursor, Claude Code).

**How to apply:** Never add secret redaction back to the persistence path. If enterprise encryption-at-rest is ever required, use OS keychain-derived encryption, not pattern-based redaction. The redaction functions still exist in `src/security/__init__.py` for transcript logger use -- that's fine, transcripts are logs not replay data.
