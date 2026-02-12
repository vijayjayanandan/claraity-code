"""Jira integration policy configuration.

Tools are automatically discovered from the Atlassian MCP server.
Read/write classification comes from MCP annotations (readOnlyHint,
destructiveHint), not hardcoded names.

This module only defines an optional blocklist for tools that should
never be exposed, regardless of what the MCP server offers.
"""

from src.integrations.mcp.policy import McpPolicyGate

# Optional blocklist: tools to explicitly block even if the MCP server
# offers them. Add prefixed names here (e.g. "jira_dangerousTool").
# Empty by default — all discovered tools are allowed.
JIRA_BLOCKLIST: set = set()


def create_jira_policy_gate() -> McpPolicyGate:
    """Create a policy gate for the Jira/Atlassian integration.

    The gate starts empty. Policies are built dynamically during
    discovery when the registry calls gate.register_tool() with
    each tool's MCP annotations.
    """
    return McpPolicyGate(blocklist=JIRA_BLOCKLIST)
