"""
Tests for PrioritizedSummarizer (deterministic fallback) and
MemoryManager._fix_orphaned_tool_calls (compaction path).

Tests cover:
- Goal/Decision extraction: full sentences, not fragments
- Code snippet filtering: skips mermaid/text/yaml, keeps real code
- Error extraction: specific patterns only, no false positives
- Current state: complete sentences, includes last user request
- Orphan tool_call fix in compaction path
"""

import pytest

from src.memory.compaction.summarizer import PrioritizedSummarizer
from src.memory.memory_manager import MemoryManager


# ============================================================
# Fixtures
# ============================================================


@pytest.fixture
def summarizer():
    return PrioritizedSummarizer(token_budget=6000)


def _make_msg(role, content, tool_calls=None, tool_call_id=None, name=None):
    """Helper to build a message dict."""
    msg = {"role": role, "content": content}
    if tool_calls:
        msg["tool_calls"] = tool_calls
    if tool_call_id:
        msg["tool_call_id"] = tool_call_id
    if name:
        msg["name"] = name
    return msg


def _user(content):
    return _make_msg("user", content)


def _assistant(content, tool_calls=None):
    return _make_msg("assistant", content, tool_calls=tool_calls)


def _tool(content, tool_call_id, name="read_file"):
    return _make_msg("tool", content, tool_call_id=tool_call_id, name=name)


# ============================================================
# Goal & Decision Extraction
# ============================================================


class TestGoalAndDecisions:
    """Decisions should be full sentences, not post-trigger fragments."""

    def test_captures_full_decision_sentence(self, summarizer):
        messages = [
            _user("Build a RAG platform"),
            _assistant(
                "I'll use ChromaDB as the vector store because it has good Python support. "
                "Let's start with the ingestion pipeline."
            ),
        ]
        section = summarizer._extract_goal_section(messages)

        assert section is not None
        # Should contain the full sentence, not just "use ChromaDB..."
        assert "ChromaDB" in section.content
        assert "vector store" in section.content

    def test_rejects_trivially_short_fragments(self, summarizer):
        """Fragments like 'build' from 'Let's build.' should be skipped."""
        messages = [
            _user("What should we do?"),
            _assistant("Let's build. We need more info first."),
        ]
        section = summarizer._extract_goal_section(messages)

        assert section is not None
        decisions_part = section.content.split("**Key Decisions:**")
        # "Let's build." is too short (< 10 chars after trigger) to be captured
        if len(decisions_part) > 1:
            assert "- build" not in decisions_part[1].lower()

    def test_goal_is_first_user_message(self, summarizer):
        messages = [
            _user("Implement user authentication"),
            _user("Also add rate limiting"),
            _assistant("I'll implement JWT-based authentication with refresh tokens."),
        ]
        section = summarizer._extract_goal_section(messages)

        assert section is not None
        assert "authentication" in section.content
        assert "**Goal:**" in section.content

    def test_no_messages_returns_none(self, summarizer):
        assert summarizer._extract_goal_section([]) is None

    def test_no_user_messages_returns_none(self, summarizer):
        messages = [_assistant("Here's an idea.")]
        assert summarizer._extract_goal_section(messages) is None

    def test_multiple_decisions_from_multiple_messages(self, summarizer):
        messages = [
            _user("Build a web app"),
            _assistant(
                "I'll use FastAPI for the backend because it supports async natively."
            ),
            _assistant(
                "We should use PostgreSQL for the database since we need ACID compliance."
            ),
        ]
        section = summarizer._extract_goal_section(messages)

        assert section is not None
        assert "FastAPI" in section.content
        assert "PostgreSQL" in section.content


# ============================================================
# Code Snippet Filtering
# ============================================================


class TestCodeSnippetFiltering:
    """Should keep real code, skip mermaid/text/yaml/json."""

    def test_keeps_python_code(self, summarizer):
        messages = [
            _assistant("Here's the function:\n```python\ndef hello():\n    return 'world'\n```"),
        ]
        section = summarizer._extract_code_section(messages, budget=1500)

        assert section is not None
        assert "def hello" in section.content

    def test_skips_mermaid_diagrams(self, summarizer):
        messages = [
            _assistant(
                "Architecture:\n```mermaid\nflowchart TD\n    A[Start] --> B[End]\n```"
            ),
        ]
        section = summarizer._extract_code_section(messages, budget=1500)

        # No code blocks should be extracted
        assert section is None

    def test_skips_json_blocks(self, summarizer):
        messages = [
            _assistant('Config:\n```json\n{"key": "value", "nested": {"a": 1}}\n```'),
        ]
        section = summarizer._extract_code_section(messages, budget=1500)

        assert section is None

    def test_skips_yaml_blocks(self, summarizer):
        messages = [
            _assistant("Config:\n```yaml\nname: test\nversion: 1.0\ndeps:\n  - foo\n```"),
        ]
        section = summarizer._extract_code_section(messages, budget=1500)

        assert section is None

    def test_skips_text_output_blocks(self, summarizer):
        messages = [
            _assistant(
                "Output:\n```text\nSome long output text that is definitely not code at all\n```"
            ),
        ]
        section = summarizer._extract_code_section(messages, budget=1500)

        assert section is None

    def test_keeps_bash_commands(self, summarizer):
        messages = [
            _assistant("Run this:\n```bash\npip install fastapi uvicorn sqlalchemy\n```"),
        ]
        section = summarizer._extract_code_section(messages, budget=1500)

        assert section is not None
        assert "pip install" in section.content

    def test_keeps_javascript(self, summarizer):
        messages = [
            _assistant(
                "Frontend:\n```javascript\nconst App = () => {\n    return <div>Hello</div>;\n};\n```"
            ),
        ]
        section = summarizer._extract_code_section(messages, budget=1500)

        assert section is not None
        assert "const App" in section.content

    def test_bare_code_block_with_code_patterns_accepted(self, summarizer):
        """Bare ``` blocks containing code-like content should be accepted."""
        messages = [
            _assistant("```\ndef foo():\n    return bar()\n```"),
        ]
        section = summarizer._extract_code_section(messages, budget=1500)

        assert section is not None
        assert "def foo" in section.content

    def test_bare_code_block_without_code_patterns_rejected(self, summarizer):
        """Bare ``` blocks without code-like patterns should be rejected."""
        messages = [
            _assistant("```\nThis is just some plain text that someone put in backticks\n```"),
        ]
        section = summarizer._extract_code_section(messages, budget=1500)

        assert section is None

    def test_prefers_recent_code_blocks(self, summarizer):
        """Should take last 5 code blocks, not first 5."""
        msgs_content = ""
        for i in range(10):
            msgs_content += f"```python\ndef func_{i}():\n    return {i}\n```\n\n"

        messages = [_assistant(msgs_content)]
        section = summarizer._extract_code_section(messages, budget=5000)

        assert section is not None
        # Last 5 of 10 = indices 5-9
        assert "func_9" in section.content
        assert "func_5" in section.content
        # First 5 (0-4) should be excluded
        assert "func_4" not in section.content
        assert "func_0" not in section.content

    def test_mixed_blocks_filters_correctly(self, summarizer):
        """Mix of mermaid + python + json should only keep python."""
        messages = [
            _assistant(
                "Diagram:\n```mermaid\nflowchart TD\n    A --> B\n```\n\n"
                "Code:\n```python\nclass MyService:\n    def run(self):\n        pass\n```\n\n"
                'Data:\n```json\n{"result": "ok", "count": 42}\n```'
            ),
        ]
        section = summarizer._extract_code_section(messages, budget=1500)

        assert section is not None
        assert "class MyService" in section.content
        assert "mermaid" not in section.content
        assert "result" not in section.content


# ============================================================
# Error Extraction
# ============================================================


class TestErrorExtraction:
    """Should catch real errors, not generic prose containing 'error'."""

    def test_catches_actual_error_report(self, summarizer):
        messages = [
            _assistant(
                "I got an error when running the tests: ModuleNotFoundError. "
                "Fixed by adding the missing import."
            ),
        ]
        section = summarizer._extract_error_section(messages, budget=600)

        assert section is not None
        assert "ModuleNotFoundError" in section.content

    def test_catches_traceback_types(self, summarizer):
        messages = [
            _assistant("TypeError: expected str but got int."),
        ]
        section = summarizer._extract_error_section(messages, budget=600)

        assert section is not None
        assert "TypeError" in section.content

    def test_catches_failed_with_pattern(self, summarizer):
        messages = [
            _assistant("The build failed with exit code 1 due to missing dependencies."),
        ]
        section = summarizer._extract_error_section(messages, budget=600)

        assert section is not None
        assert "failed with" in section.content.lower()

    def test_catches_fix_report(self, summarizer):
        messages = [
            _assistant("Fixed by updating the import path to the new module location."),
        ]
        section = summarizer._extract_error_section(messages, budget=600)

        assert section is not None
        assert "Fixed by" in section.content

    def test_rejects_generic_architecture_prose(self, summarizer):
        """'easy to debug' and 'easy to fix' should NOT be captured."""
        messages = [
            _assistant(
                "This architecture is designed to be deterministic first, "
                "production-friendly, observable, easy to debug, and easy to extend."
            ),
        ]
        section = summarizer._extract_error_section(messages, budget=600)

        # Should not find any errors in generic architectural prose
        assert section is None

    def test_rejects_issue_in_generic_context(self, summarizer):
        """'The main issue with X is Y' style prose is not an error report."""
        messages = [
            _assistant(
                "The main issue with pure embedding retrieval is precision at top-k. "
                "Many architectures get this wrong."
            ),
        ]
        section = summarizer._extract_error_section(messages, budget=600)

        assert section is None

    def test_rejects_error_prevention_prose(self, summarizer):
        """Describing how to prevent errors is not an error report."""
        messages = [
            _assistant(
                "Using structured logging prevents error tracking issues. "
                "The system is designed to fix itself when problems occur."
            ),
        ]
        section = summarizer._extract_error_section(messages, budget=600)

        assert section is None

    def test_deduplicates_similar_errors(self, summarizer):
        messages = [
            _assistant(
                "Got an error: ImportError cannot find module foo. "
                "Got an error: ImportError cannot find module bar. "
                "Got an error: ImportError cannot find module baz."
            ),
        ]
        section = summarizer._extract_error_section(messages, budget=600)

        assert section is not None
        # All three start differently after first 50 chars, so they should be separate
        # But the pattern should still limit total to <= 5

    def test_no_errors_returns_none(self, summarizer):
        messages = [
            _assistant("Everything is working perfectly. All tests pass."),
        ]
        section = summarizer._extract_error_section(messages, budget=600)

        assert section is None


# ============================================================
# Current State Extraction
# ============================================================


class TestCurrentStateExtraction:
    """Should produce complete sentences, not mid-sentence slices."""

    def test_extracts_complete_sentences(self, summarizer):
        messages = [
            _user("Fix the tests"),
            _assistant(
                "I found three broken tests. The first one had a wrong import. "
                "The second had a stale mock. I fixed both and they pass now."
            ),
        ]
        section = summarizer._extract_current_state_section(messages, budget=400)

        assert section is not None
        # Should not start with "..." or have cut-off text
        assert "..." not in section.content or section.content.count("...") <= 1
        # Should contain complete sentences
        assert "I fixed both" in section.content

    def test_includes_last_user_request(self, summarizer):
        messages = [
            _assistant("Done with the refactor."),
            _user("Now add unit tests for the new module"),
        ]
        section = summarizer._extract_current_state_section(messages, budget=400)

        assert section is not None
        assert "unit tests" in section.content
        assert "**Last user request:**" in section.content

    def test_includes_last_action(self, summarizer):
        messages = [
            _user("Fix it"),
            _assistant("I updated the config file and restarted the service."),
        ]
        section = summarizer._extract_current_state_section(messages, budget=400)

        assert section is not None
        assert "**Last action:**" in section.content
        assert "config file" in section.content

    def test_handles_long_assistant_message(self, summarizer):
        """Long messages should take last few sentences, not random tail."""
        long_msg = "First sentence. " * 50 + "Important final conclusion here."
        messages = [
            _user("Analyze this"),
            _assistant(long_msg),
        ]
        section = summarizer._extract_current_state_section(messages, budget=400)

        assert section is not None
        assert "Important final conclusion" in section.content

    def test_no_messages_returns_none(self, summarizer):
        assert summarizer._extract_current_state_section([], budget=400) is None

    def test_only_tool_messages_returns_none(self, summarizer):
        messages = [
            _tool("file content", "tc_123"),
        ]
        assert summarizer._extract_current_state_section(messages, budget=400) is None

    def test_truncates_long_user_request(self, summarizer):
        messages = [
            _assistant("Done."),
            _user("x" * 500),
        ]
        section = summarizer._extract_current_state_section(messages, budget=400)

        assert section is not None
        # User message should be truncated with ...
        assert "..." in section.content


# ============================================================
# Full Deterministic Summary
# ============================================================


class TestFullDeterministicSummary:
    """Integration test for the complete deterministic path."""

    def test_produces_all_sections(self, summarizer):
        messages = [
            _user("Build a REST API with FastAPI"),
            _assistant(
                "I'll use FastAPI with SQLAlchemy for the ORM because it has async support. "
                "Here's the initial code:\n"
                "```python\nfrom fastapi import FastAPI\napp = FastAPI()\n"
                "@app.get('/health')\ndef health():\n    return {'status': 'ok'}\n```\n"
                "I encountered a TypeError: missing argument 'title'. "
                "Fixed by adding the title parameter to FastAPI()."
            ),
            _assistant(
                "I updated `src/api/main.py` and `src/config.py`.",
                tool_calls=[
                    {"id": "tc_1", "function": {"name": "write_file", "arguments": '{"file_path": "src/api/main.py"}'}}
                ],
            ),
            _tool("File written", "tc_1", "write_file"),
            _user("Add authentication next"),
            _assistant("I'll add JWT authentication to protect the endpoints."),
        ]

        summary = summarizer._generate_deterministic_summary(messages)

        assert "## Goal and Key Decisions" in summary
        assert "## All User Messages" in summary
        assert "## Code Snippets" in summary
        assert "## Current State" in summary
        assert "FastAPI" in summary
        assert "Build a REST API" in summary

    def test_empty_messages_returns_fallback(self, summarizer):
        summary = summarizer._generate_deterministic_summary([])
        assert summary == "Conversation history compacted."


# ============================================================
# Orphan Tool Call Fix (MemoryManager._fix_orphaned_tool_calls)
# ============================================================


class TestOrphanToolCallFix:
    """Test the static orphan-fix method on MemoryManager."""

    def test_no_orphans_returns_unchanged(self):
        context = [
            _user("read file"),
            _assistant(
                "Reading...",
                tool_calls=[{"id": "tc_1", "function": {"name": "read_file"}}],
            ),
            _tool("file content here", "tc_1", "read_file"),
            _assistant("Done."),
        ]
        result = MemoryManager._fix_orphaned_tool_calls(context)

        assert len(result) == len(context)
        roles = [m["role"] for m in result]
        assert roles == ["user", "assistant", "tool", "assistant"]

    def test_creates_synthetic_for_orphan(self):
        context = [
            _user("read file"),
            _assistant(
                "Reading...",
                tool_calls=[{"id": "tc_1", "function": {"name": "read_file"}}],
            ),
            # Missing tool result for tc_1!
            _assistant("Something happened."),
        ]
        result = MemoryManager._fix_orphaned_tool_calls(context)

        # Should now have 4 messages: user, assistant(tool_call), tool(synthetic), assistant
        assert len(result) == 4
        synthetic = result[2]
        assert synthetic["role"] == "tool"
        assert synthetic["tool_call_id"] == "tc_1"
        assert "interrupted" in synthetic["content"].lower()

    def test_preserves_existing_results_in_order(self):
        context = [
            _assistant(
                "",
                tool_calls=[
                    {"id": "tc_1", "function": {"name": "read_file"}},
                    {"id": "tc_2", "function": {"name": "write_file"}},
                ],
            ),
            _tool("content of file", "tc_1", "read_file"),
            _tool("wrote file", "tc_2", "write_file"),
            _user("thanks"),
        ]
        result = MemoryManager._fix_orphaned_tool_calls(context)

        # No orphans, so structure should be preserved
        assert len(result) == 4
        assert result[0]["role"] == "assistant"
        assert result[1]["role"] == "tool"
        assert result[1]["tool_call_id"] == "tc_1"
        assert result[2]["role"] == "tool"
        assert result[2]["tool_call_id"] == "tc_2"
        assert result[3]["role"] == "user"

    def test_fixes_multiple_orphans(self):
        context = [
            _assistant(
                "",
                tool_calls=[
                    {"id": "tc_1", "function": {"name": "read_file"}},
                    {"id": "tc_2", "function": {"name": "write_file"}},
                ],
            ),
            # Both tool results missing!
            _user("what happened?"),
        ]
        result = MemoryManager._fix_orphaned_tool_calls(context)

        # Should be: assistant, tool(tc_1 synthetic), tool(tc_2 synthetic), user
        assert len(result) == 4
        tool_msgs = [m for m in result if m["role"] == "tool"]
        assert len(tool_msgs) == 2
        tc_ids = {m["tool_call_id"] for m in tool_msgs}
        assert tc_ids == {"tc_1", "tc_2"}

    def test_reorders_misplaced_tool_results(self):
        """Tool results that appear away from their assistant message
        should be reordered to immediately follow the assistant."""
        context = [
            _assistant(
                "",
                tool_calls=[{"id": "tc_1", "function": {"name": "read_file"}}],
            ),
            _user("interruption"),
            _tool("file content", "tc_1", "read_file"),
        ]
        result = MemoryManager._fix_orphaned_tool_calls(context)

        # Tool result should be right after assistant, before user
        assert result[0]["role"] == "assistant"
        assert result[1]["role"] == "tool"
        assert result[1]["tool_call_id"] == "tc_1"
        assert result[2]["role"] == "user"

    def test_empty_context(self):
        assert MemoryManager._fix_orphaned_tool_calls([]) == []

    def test_no_tool_calls_at_all(self):
        context = [
            _user("hello"),
            _assistant("hi there"),
        ]
        result = MemoryManager._fix_orphaned_tool_calls(context)

        assert len(result) == 2
        assert result[0]["role"] == "user"
        assert result[1]["role"] == "assistant"


# ============================================================
# User Messages Section (unchanged, but test for regressions)
# ============================================================


class TestUserMessagesSection:
    """Ensure user messages are still preserved verbatim."""

    def test_preserves_all_user_messages(self, summarizer):
        messages = [
            _user("First request"),
            _assistant("Response 1"),
            _user("Second request"),
            _assistant("Response 2"),
            _user("Third request"),
        ]
        section = summarizer._extract_user_messages_section(messages, budget=2000)

        assert section is not None
        assert "First request" in section.content
        assert "Second request" in section.content
        assert "Third request" in section.content

    def test_numbered_in_order(self, summarizer):
        messages = [
            _user("Alpha"),
            _assistant("..."),
            _user("Beta"),
        ]
        section = summarizer._extract_user_messages_section(messages, budget=2000)

        assert section is not None
        assert section.content.index("1.") < section.content.index("2.")
        assert section.content.index("Alpha") < section.content.index("Beta")


# ============================================================
# Files Modified Section (unchanged, test for regressions)
# ============================================================


class TestFilesModifiedSection:

    def test_extracts_files_from_tool_calls(self, summarizer):
        messages = [
            _assistant(
                "",
                tool_calls=[{
                    "id": "tc_1",
                    "function": {
                        "name": "write_file",
                        "arguments": '{"file_path": "src/api/main.py"}',
                    },
                }],
            ),
            _tool("ok", "tc_1", "write_file"),
        ]
        section = summarizer._extract_files_section(messages, budget=400)

        assert section is not None
        assert "src/api/main.py" in section.content

    def test_extracts_backtick_file_paths(self, summarizer):
        messages = [
            _assistant("I updated `src/config.py` and `tests/test_config.py`."),
        ]
        section = summarizer._extract_files_section(messages, budget=400)

        assert section is not None
        assert "src/config.py" in section.content
        assert "tests/test_config.py" in section.content
