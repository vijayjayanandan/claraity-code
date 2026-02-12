"""MCP (Model Context Protocol) integration layer.

Provides transport-agnostic client, schema adaptation, policy gating,
and a bridge that makes MCP tools indistinguishable from native tools.

Imports are lazy to avoid circular import chains
(adapter -> llm.base -> session -> core -> llm).
Use direct module imports: `from src.integrations.mcp.client import McpClient`
"""

__all__ = [
    "McpClient",
    "McpTransport",
    "McpToolAdapter",
    "McpPolicyGate",
    "ToolPolicy",
    "McpBridgeTool",
    "McpToolRegistry",
    "McpServerConfig",
    "McpConnectionManager",
]
