"""
Shared test fixtures for core agent tests.

Provides:
- live_agent: Factory that builds CodingAgent using real API (config.yaml + keyring)
- MockUIProtocol: Mock for approval/pause flows in stream_response tests
- make_tool_call: Helper to create ToolCall objects
"""

import asyncio
import json
import os
import uuid
import yaml
from pathlib import Path
from typing import Any, Dict, List, Optional

import pytest

from src.session.models.message import ToolCall, ToolCallFunction


# ---------------------------------------------------------------------------
# API Configuration (same pattern as test_prompt_caching.py)
# ---------------------------------------------------------------------------

def _load_api_config() -> Dict[str, Any]:
    """Load API config from .clarity/config.yaml + credential_store, like the real agent."""
    project_root = Path(__file__).resolve().parent.parent.parent
    config_path = project_root / ".clarity" / "config.yaml"

    if config_path.exists():
        with open(config_path, "r") as f:
            config = yaml.safe_load(f)
        llm_config = config.get("llm", {})
        base_url = llm_config.get("base_url", "")
        model = llm_config.get("model", "")
        context_window = llm_config.get("context_window", 128000)
    else:
        base_url = os.getenv("LLM_HOST", "")
        model = os.getenv("LLM_MODEL", "")
        context_window = int(os.getenv("MAX_CONTEXT_TOKENS", "128000"))

    # Load API key from OS keyring first, then env var
    api_key = ""
    try:
        from src.llm.credential_store import load_api_key
        api_key = load_api_key() or ""
    except (ImportError, Exception):
        pass
    if not api_key:
        api_key = os.getenv("OPENAI_API_KEY", "")

    return {
        "backend": "openai",
        "model_name": model,
        "base_url": base_url,
        "context_window": context_window,
        "api_key": api_key,
        "load_file_memories": False,
    }


API_CONFIG = _load_api_config()


def _has_valid_api() -> bool:
    """Check if we have valid API credentials for live tests."""
    if os.getenv("SKIP_INTEGRATION_TESTS"):
        return False
    return bool(API_CONFIG.get("api_key") and API_CONFIG.get("base_url"))


# Skip marker for tests requiring a real API
requires_api = pytest.mark.skipif(
    not _has_valid_api(),
    reason="No API key or base_url configured (need .clarity/config.yaml or env vars)",
)


# ---------------------------------------------------------------------------
# MockUIProtocol
# ---------------------------------------------------------------------------

class MockUIProtocol:
    """
    Mock UIProtocol for testing stream_response.

    Args:
        auto_approve: If True, auto-approve all tool calls.
        auto_continue: If True, auto-continue at pause prompts.
    """

    def __init__(self, auto_approve: bool = True, auto_continue: bool = False):
        self._auto_approve = auto_approve
        self._auto_continue = auto_continue
        self._interrupted = False
        self._approval_decisions = {}  # call_id -> bool
        self._rejection_feedback = {}  # call_id -> Optional[str]
        self._on_todos_updated = None
        self.approval_requests = []
        self.pause_requests = []

    def check_interrupted(self) -> bool:
        return self._interrupted

    def set_interrupted(self):
        self._interrupted = True

    def has_pause_capability(self) -> bool:
        return True

    async def wait_for_approval(self, call_id, tool_name, timeout=None, force_approval=False):
        from src.core.protocol import ApprovalResult
        self.approval_requests.append((call_id, tool_name))
        approved = self._approval_decisions.get(call_id, self._auto_approve)
        feedback = self._rejection_feedback.get(call_id) if not approved else None
        return ApprovalResult(
            call_id=call_id,
            approved=approved,
            auto_approve_future=False,
            feedback=feedback,
        )

    async def wait_for_pause_response(self, timeout=None):
        from src.core.protocol import PauseResult
        self.pause_requests.append(True)
        return PauseResult(continue_work=self._auto_continue)

    async def wait_for_clarify_response(self, call_id, timeout=None):
        from src.core.protocol import ClarifyResult
        return ClarifyResult(call_id=call_id, submitted=False)

    async def wait_for_plan_approval(self, plan_hash, timeout=None):
        from src.core.protocol import PlanApprovalResult
        return PlanApprovalResult(plan_hash=plan_hash, approved=True)

    def notify_todos_updated(self, todos):
        if self._on_todos_updated:
            self._on_todos_updated(todos)

    def reset(self):
        self._interrupted = False

    def set_rejection(self, call_id: str, with_feedback: Optional[str] = None):
        """Pre-configure a rejection for a specific call_id."""
        self._approval_decisions[call_id] = False
        self._rejection_feedback[call_id] = with_feedback


# ---------------------------------------------------------------------------
# live_agent factory
# ---------------------------------------------------------------------------

@pytest.fixture
def live_agent(tmp_path):
    """
    Factory fixture that builds a CodingAgent using real API config.

    Usage:
        agent = live_agent()
        agent = live_agent(permission_mode="plan")
    """
    def _factory(permission_mode: str = "auto", **overrides):
        from src.core.agent import CodingAgent
        from src.llm.config_loader import LLMConfigData

        config_data = LLMConfigData(
            model=API_CONFIG.get("model_name", ""),
            backend_type=API_CONFIG.get("backend", "openai"),
            base_url=API_CONFIG.get("base_url", ""),
            context_window=API_CONFIG.get("context_window", 131072),
            api_key=API_CONFIG.get("api_key", ""),
        )

        agent = CodingAgent.from_config(
            config_data,
            working_directory=str(tmp_path),
            permission_mode=permission_mode,
            load_file_memories=API_CONFIG.get("load_file_memories", False),
        )

        return agent

    return _factory


# ---------------------------------------------------------------------------
# Helper: make a ToolCall
# ---------------------------------------------------------------------------

def make_tool_call(
    name: str,
    arguments: Optional[Dict[str, Any]] = None,
    call_id: Optional[str] = None,
) -> ToolCall:
    """Create a ToolCall with given name and arguments."""
    return ToolCall(
        id=call_id or f"call_{uuid.uuid4().hex[:8]}",
        function=ToolCallFunction(
            name=name,
            arguments=json.dumps(arguments or {}),
        ),
    )
