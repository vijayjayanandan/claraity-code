# MCP Integration Infrastructure

Comprehensive documentation for the Model Context Protocol (MCP) integration layer in ClarAIty.

## Table of Contents

1. [Architecture Overview](#1-architecture-overview)
2. [Data Flow](#2-data-flow)
3. [Module Reference](#3-module-reference)
4. [Security Model](#4-security-model)
5. [Connection Lifecycle](#5-connection-lifecycle)
6. [Jira Integration](#6-jira-integration)
7. [Adding a New Integration](#7-adding-a-new-integration)
8. [Testing](#8-testing)
9. [Troubleshooting](#9-troubleshooting)

---

## 1. Architecture Overview

The MCP layer makes external service tools (Jira, GitHub, etc.) indistinguishable from native agent tools. The LLM sees a flat list of tools -- it never knows which are native and which come from MCP servers.

### Design Principles

| Principle | How |
|---|---|
| **Transport agnostic** | Abstract `McpTransport` supports SSE (remote) and stdio (local subprocess) |
| **Zero overhead when unused** | No MCP code runs until `/connect-jira` (or similar) is invoked |
| **Annotation-driven security** | Read/write classification from MCP server annotations, not hardcoded names |
| **Multi-connection** | `McpConnectionManager` tracks named connections (jira, github, etc.) |
| **Clean shutdown** | Dual path: async graceful + sync emergency for Windows subprocess cleanup |

### Layer Diagram

```
                         CodingAgent
                             |
                     McpConnectionManager          <-- lifecycle manager
                      /        |        \
               McpConnection  McpConnection  ...   <-- per-server bundles
                  |               |
             McpToolRegistry  McpToolRegistry       <-- discovery + caching
                  |               |
             McpBridgeTool   McpBridgeTool  ...    <-- Tool subclasses in ToolExecutor
                  |               |
              McpClient       McpClient             <-- JSON-RPC + MCP handshake
                  |               |
            McpTransport     McpTransport           <-- SSE or Stdio
```

### File Map

```
src/integrations/
|-- secrets.py                    # SecretStore abstraction (keyring + encrypted file)
|-- mcp/
|   |-- __init__.py               # Public exports (lazy imports)
|   |-- config.py                 # McpServerConfig dataclass
|   |-- client.py                 # McpTransport ABC, SseTransport, StdioTransport, McpClient
|   |-- adapter.py                # McpToolAdapter (MCP schema <-> ToolDefinition)
|   |-- bridge.py                 # McpBridgeTool (Tool subclass that proxies to MCP)
|   |-- policy.py                 # ToolPolicy + McpPolicyGate (annotation-based)
|   |-- registry.py               # McpToolRegistry (discovery, caching, registration)
|   |-- manager.py                # McpConnectionManager (multi-connection lifecycle)
|-- jira/
    |-- __init__.py               # Module docstring
    |-- connection.py             # JiraConnection (config persistence, npx check)
    |-- tools.py                  # Jira blocklist + policy gate factory
```

---

## 2. Data Flow

### Connect Flow

```
User: /connect-jira
  |
  v
app._connect_jira()
  |-- JiraConnection.get_mcp_config()          --> McpServerConfig
  |-- McpClient(config, StdioTransport())      --> client
  |-- McpToolRegistry(config, policy_gate)     --> registry
  |
  v
agent.enable_mcp_integration("jira", registry, client)
  |
  v
McpConnectionManager.connect("jira", ...)
  |-- client.connect()                         --> MCP handshake (initialize + initialized)
  |-- registry.discover_and_register()
  |     |-- client.list_tools()                --> 34 raw tool schemas from Atlassian
  |     |-- adapter.adapt_schemas()            --> ToolDefinition objects (prefixed "jira_*")
  |     |-- policy_gate.register_tool()        --> ToolPolicy from annotations per tool
  |     |-- McpBridgeTool(...)                 --> Tool subclass per allowed tool
  |     |-- tool_executor.register_tool()      --> registered like native tools
  |
  v
McpConnection stored in manager._connections["jira"]
```

### Tool Execution Flow

```
LLM returns tool_call: {"name": "jira_searchJiraIssuesUsingJql", "arguments": {...}}
  |
  v
agent.execute_tool()
  |-- tool_executor.tools["jira_searchJiraIssuesUsingJql"]  --> McpBridgeTool
  |
  v
McpBridgeTool.execute(**kwargs)
  |-- _invoke_on_loop(kwargs)
  |     |-- asyncio.run_coroutine_threadsafe(coro, original_loop)
  |
  v
McpBridgeTool._async_invoke(kwargs)
  |-- client.invoke("searchJiraIssuesUsingJql", kwargs)     --> JSON-RPC tools/call
  |-- adapter.adapt_result(tool_name, raw_result)           --> ToolResult
  |
  v
ToolResult returned to agent (same format as native tools)
```

### Disconnect Flow

```
User: /disconnect-jira                     User: Ctrl+Q (exit TUI)
  |                                           |
  v                                           v
agent.disable_mcp_integration("jira")     app.on_unmount()
  |                                           |
  v                                           v
manager.disconnect("jira", tool_executor)  manager.shutdown_sync()
  |-- unregister bridge tools                 |-- for each connection:
  |-- registry.clear()                        |     |-- client.close_sync()
  |-- client.disconnect() (async)             |     |     |-- neutralize asyncio transports
  |                                           |     |     |-- kill subprocess
  v                                           |     |-- registry.clear()
Connection removed                            |-- _connections.clear()
                                              v
                                           All connections killed (no event loop needed)
```

---

## 3. Module Reference

### config.py -- McpServerConfig

Centralized configuration dataclass. All timeouts, truncation limits, and auth settings live here.

```python
@dataclass
class McpServerConfig:
    name: str                          # "atlassian-rovo"
    server_url: Optional[str]          # For SSE transport (remote servers)
    command: Optional[str]             # For stdio transport (local subprocess)
    connect_timeout: float = 30.0
    invoke_timeout: float = 60.0
    discovery_timeout: float = 30.0
    max_result_chars: int = 8192       # Result truncation limit
    max_result_items: int = 50
    cache_ttl_seconds: float = 3600.0  # Discovery cache TTL (1 hour)
    auth_header_name: str = "Authorization"
    auth_secret_key: str = ""          # Key in SecretStore (empty = no auth)
    extra_headers: Dict[str, str]      # Non-secret headers
    tool_prefix: str = ""              # "jira" -> tools become "jira_*"
```

### client.py -- Transport + Client

**McpTransport** (ABC): Defines the transport interface.

| Method | Purpose |
|---|---|
| `connect(config, auth_headers)` | Establish connection |
| `send(method, params)` | JSON-RPC request/response |
| `send_notification(method, params)` | JSON-RPC notification (no response) |
| `disconnect()` | Async graceful close |
| `close_sync()` | Sync emergency close (override in subclasses) |
| `is_connected()` | Connection status check |

**SseTransport**: HTTP-based for remote MCP servers. Auth headers injected per-request (not baked into httpx client).

**StdioTransport**: Subprocess-based for local MCP proxies (e.g. `npx mcp-remote`).

Key detail -- `close_sync()` neutralizes asyncio internals on Windows:
- Sets `BaseSubprocessTransport._closed = True` to prevent `__del__` from calling `close()`
- Sets `_ProactorBasePipeTransport._sock = None` and `._closing = True` to prevent `__del__` warnings
- Closes OS-level pipe handles directly
- Kills the subprocess

**McpClient**: Owns the transport. Handles MCP protocol handshake (`initialize` + `notifications/initialized`) and dispatches `tools/list` and `tools/call`.

Auth tokens are resolved from SecretStore at connect time and passed to the transport. The token is **never stored on McpClient**.

### adapter.py -- McpToolAdapter

Bidirectional translation between MCP and internal formats.

| Method | Direction | Purpose |
|---|---|---|
| `adapt_schema(mcp_tool)` | MCP -> Internal | Raw MCP schema to `ToolDefinition` (adds prefix) |
| `adapt_schemas(mcp_tools)` | MCP -> Internal | Batch conversion |
| `adapt_result(name, result)` | MCP -> Internal | MCP content blocks to `ToolResult` (with truncation) |
| `strip_prefix(name)` | Internal -> MCP | Remove prefix for invoke calls |

Tool name prefix uses `_` separator (not `.`, which is invalid in Claude API tool names). Example: `jira_searchJiraIssuesUsingJql`.

MCP content block types handled: `text`, `resource` (URI + text), unknown (serialized as JSON).

### bridge.py -- McpBridgeTool

Extends the native `Tool` base class so MCP tools register in `ToolExecutor` identically to native tools. The LLM sees no difference.

**Event loop strategy** (critical for TUI):
1. `ToolExecutor.execute_tool_async()` runs sync `Tool.execute()` in a `ThreadPoolExecutor`
2. `McpBridgeTool.execute()` dispatches the async MCP invoke back to the **original** event loop via `asyncio.run_coroutine_threadsafe()`
3. This keeps httpx on the loop it was created on (avoids connection pool mismatch)
4. Fallback: creates a new event loop for testing/sync contexts

### policy.py -- ToolPolicy + McpPolicyGate

**ToolPolicy** (frozen dataclass): Policy for a single tool.

| Field | Type | Meaning |
|---|---|---|
| `allowed` | bool | Exposed to LLM? |
| `requires_approval` | bool | User must confirm before execution? |
| `is_write` | bool | Modifies external state? |
| `is_destructive` | bool | Destructive operation? |

**Policy derivation from MCP annotations:**

| Annotation | Value | Classification |
|---|---|---|
| `readOnlyHint: True` | Read-only | No approval needed |
| `readOnlyHint: False` | Write | Approval required |
| `destructiveHint: True` | Destructive | Approval always required |
| (missing annotations) | Unknown | Assumed write (conservative) |

**McpPolicyGate**: Registers tools during discovery, builds policies from annotations, supports optional blocklist.

```python
gate = McpPolicyGate(blocklist={"jira_deleteProject"})
policy = gate.register_tool("jira_searchIssues", {"readOnlyHint": True})
# policy.allowed=True, policy.requires_approval=False, policy.is_write=False
```

### registry.py -- McpToolRegistry

Manages the full discovery-to-registration pipeline for one MCP server:

1. **Discover**: Fetch tool schemas from MCP server (`tools/list`)
2. **Adapt**: Convert MCP schemas to `ToolDefinition` objects
3. **Filter**: Register each tool in policy gate; skip blocked tools
4. **Register**: Create `McpBridgeTool` per tool, register in `ToolExecutor`
5. **Cache**: Store results with configurable TTL to avoid re-discovery

Key properties:
- `enabled` -- True after successful discovery
- `_mcp_tool_names` -- Set of registered prefixed names (used for cleanup)
- `_tool_definitions` -- Cached `ToolDefinition` list for LLM requests

### manager.py -- McpConnectionManager

Centralized lifecycle manager for **all** MCP connections. Replaces ad-hoc `_mcp_client` / `_mcp_registry` attributes.

**McpConnection** (dataclass): Bundles all objects for one server connection.

```python
@dataclass
class McpConnection:
    name: str                  # "jira", "github"
    config: McpServerConfig
    client: McpClient
    registry: McpToolRegistry
    tool_names: Set[str]       # snapshot for cleanup on disconnect
```

**McpConnectionManager methods:**

| Method | Type | Purpose |
|---|---|---|
| `connect(name, config, client, registry, tool_executor)` | async | Connect server, discover tools, register |
| `disconnect(name, tool_executor)` | async | Graceful disconnect, unregister tools |
| `shutdown(tool_executor)` | async | Disconnect ALL connections gracefully |
| `shutdown_sync()` | sync | Emergency kill all subprocesses |
| `is_mcp_tool(tool_name)` | sync | Check across all connections |
| `requires_approval(tool_name)` | sync | Route to correct policy gate |
| `get_all_tool_definitions()` | sync | Aggregate from all registries |
| `has_connections` | property | True if any active connections |
| `connection_names` | property | List of active names |

### secrets.py -- SecretStore

Pluggable secret storage with two backends:

| Backend | Storage | Use Case |
|---|---|---|
| `KeyringSecretStore` | OS keychain (Windows Credential Manager, macOS Keychain) | Preferred |
| `EncryptedFileSecretStore` | AES-256 Fernet encrypted file | Fallback (headless environments) |

`get_secret_store()` factory tries keyring first, falls back to encrypted file.

File layout:
- `.clarity/secrets/secrets.enc` -- Encrypted JSON blob
- `.clarity/secrets/secret.key` -- Fernet key (auto-generated)

---

## 4. Security Model

### Auth Token Handling

```
SecretStore.get(key)
     |
     v
  token (ephemeral)
     |
     v
McpClient.connect(secret_store)
  |-- resolves token
  |-- passes to transport.connect(config, auth_headers)
  |-- DOES NOT store token on self
     |
     v
Transport holds auth_headers for per-request injection
  |-- cleared on disconnect()
```

**Rules:**
- Tokens never appear in logs, MessageStore, JSONL, or ToolResult output
- Tokens never stored on McpClient (only transport holds them)
- Tokens cleared from memory on disconnect
- Config files (`.clarity/integrations/jira.json`) contain zero secrets

### Tool Approval

```
LLM wants to call "jira_createJiraIssueUsingJql"
     |
     v
agent checks: mcp_manager.requires_approval("jira_createJiraIssueUsingJql")
     |-- routes to jira connection's policy gate
     |-- policy gate checks: is_write=True -> requires_approval=True
     |
     v
TUI shows approval widget: "Allow jira_createJiraIssueUsingJql?"
     |
     v
User approves -> tool executes
User denies -> tool returns error
```

### Blocklist

Per-integration blocklist for dangerous tools:

```python
# src/integrations/jira/tools.py
JIRA_BLOCKLIST: set = set()  # Empty by default; add tool names to block

# Example: block destructive tools
JIRA_BLOCKLIST = {"jira_deleteProject", "jira_bulkDeleteIssues"}
```

---

## 5. Connection Lifecycle

### Three Exit Scenarios

| Scenario | Trigger | Cleanup Path |
|---|---|---|
| **Graceful exit** | Ctrl+Q | `on_unmount()` -> `shutdown_sync()` -> kills subprocesses synchronously |
| **Window close** | Click X | OS signal -> `on_unmount()` may fire -> same as graceful |
| **Hard kill** | Task manager / kill -9 | OS reclaims all resources; no cleanup code runs |

### Why `shutdown_sync()` Exists

Textual's `on_unmount()` is synchronous. The event loop is closing. `asyncio.create_task()` schedules work that never runs. `shutdown_sync()` solves this by:

1. Setting `BaseSubprocessTransport._closed = True` (prevents `__del__` from using dead loop)
2. Setting `_ProactorBasePipeTransport._sock = None` (prevents `__del__` ResourceWarning)
3. Closing OS-level pipe handles directly
4. Calling `process.kill()` to terminate the subprocess
5. Clearing all connection state

Without this, Python GC fires `__del__` on transport objects after the loop closes, producing `RuntimeError: Event loop is closed` on Windows.

---

## 6. Jira Integration

### How It Works

Jira uses Atlassian's **Remote MCP Server** at `https://mcp.atlassian.com/v1/mcp`. Auth is handled by OAuth 2.1 via the `mcp-remote` npm proxy.

```
ClarAIty Agent
     |
     | stdin/stdout (JSON-RPC)
     v
npx mcp-remote https://mcp.atlassian.com/v1/mcp
     |
     | HTTPS (OAuth 2.1)
     v
Atlassian Remote MCP Server
     |
     v
Jira Cloud REST API
```

**First connect**: `mcp-remote` opens a browser for Atlassian OAuth consent. Tokens are cached locally by the proxy.

**Subsequent connects**: Tokens are reused automatically.

### Configuration

```json
// .clarity/integrations/jira.json (no secrets)
{
  "cloud_url": "https://mycompany.atlassian.net",
  "enabled": true
}
```

### Available Tools (34 from Atlassian)

Examples of what's discovered:

| Tool (prefixed) | Annotations | Approval? |
|---|---|---|
| `jira_searchJiraIssuesUsingJql` | readOnlyHint: true | No |
| `jira_getJiraIssueDetails` | readOnlyHint: true | No |
| `jira_createJiraIssue` | readOnlyHint: false | Yes |
| `jira_updateJiraIssue` | readOnlyHint: false | Yes |

### Prerequisites

- Node.js and npm installed (`npx` on PATH)
- Atlassian Cloud account with Jira access
- Internet connectivity for OAuth flow and API calls

---

## 7. Adding a New Integration

### Step 1: Create the integration module

```
src/integrations/github/
|-- __init__.py
|-- connection.py    # GitHubConnection (config persistence, prerequisite checks)
|-- tools.py         # GitHub blocklist + policy gate factory
```

**connection.py**: Manage config persistence and build `McpServerConfig`.

```python
class GitHubConnection:
    def get_mcp_config(self) -> McpServerConfig:
        return McpServerConfig(
            name="github-mcp",
            command="npx -y @github/mcp-server",  # or server_url for SSE
            tool_prefix="gh",
            connect_timeout=30.0,
            invoke_timeout=60.0,
            cache_ttl_seconds=3600.0,
        )
```

**tools.py**: Define any tools to block.

```python
from src.integrations.mcp.policy import McpPolicyGate

GITHUB_BLOCKLIST: set = set()

def create_github_policy_gate() -> McpPolicyGate:
    return McpPolicyGate(blocklist=GITHUB_BLOCKLIST)
```

### Step 2: Add TUI command in app.py

Add a `/connect-github` command handler following the same pattern as `_connect_jira()`:

```python
async def _connect_github(self):
    conn = GitHubConnection()
    config = conn.get_mcp_config()
    transport = StdioTransport()
    client = McpClient(config, transport)
    policy_gate = create_github_policy_gate()
    registry = McpToolRegistry(config, policy_gate)
    count = await self.agent.enable_mcp_integration(
        "github", registry, client
    )
```

### Step 3: No agent changes needed

The `McpConnectionManager` handles multiple connections automatically. `enable_mcp_integration("github", ...)` stores a new named connection alongside existing ones.

### Step 4: Add tests

Create `tests/integrations/test_github_connection.py` with mock transports (follow `test_mcp_manager.py` patterns).

---

## 8. Testing

### Test Suite

```bash
# All integration tests
pytest tests/integrations/ -v

# Specific module
pytest tests/integrations/test_mcp_manager.py -v
pytest tests/integrations/test_mcp_bridge.py -v
```

### Test Files

| File | Tests | Coverage |
|---|---|---|
| `test_mcp_adapter.py` | 17 | Schema translation, result normalization, truncation, prefix handling |
| `test_mcp_policy.py` | 17 | Annotation-based policy, blocklist, lifecycle, Jira factory |
| `test_mcp_bridge.py` | 13 | Bridge execution, error handling, registry discovery, caching |
| `test_mcp_manager.py` | 18 | Connect/disconnect, shutdown (async + sync), tool routing, transport neutralization |
| `test_secrets.py` | 18 | Encrypted storage, keyring, leak prevention |
| **Total** | **83** | |

### Mock Transport Pattern

Tests use `AsyncMock(spec=McpTransport)` to simulate MCP servers without real subprocesses:

```python
def _make_mock_transport(tool_schemas=None):
    transport = AsyncMock(spec=McpTransport)
    transport.is_connected.return_value = True
    transport.close_sync = MagicMock()

    async def mock_send(method, params=None):
        if method == "tools/list":
            return {"tools": tool_schemas or [...]}
        elif method == "tools/call":
            return {"content": [{"type": "text", "text": "ok"}], "isError": False}
        return {}

    transport.send.side_effect = mock_send
    return transport
```

### Circular Import Prevention

`tests/integrations/conftest.py` pre-loads `src.core` to resolve the circular import chain that would otherwise break test collection:

```python
# conftest.py
import src.core  # noqa: F401 -- resolve circular import for test collection
```

---

## 9. Troubleshooting

### "Event loop is closed" on exit

**Symptom**: `RuntimeError: Event loop is closed` or `ValueError: I/O operation on closed pipe` when exiting TUI after connecting to an MCP server.

**Cause**: asyncio transport `__del__` methods fire after the event loop closes.

**Fix**: `StdioTransport.close_sync()` neutralizes asyncio transport internals. This is called via `McpConnectionManager.shutdown_sync()` in `app.on_unmount()`.

### Tool name validation error

**Symptom**: `tools.N.custom.name: String should match pattern '^[a-zA-Z0-9_-]{1,128}$'`

**Cause**: Tool name prefix separator was `.` (dot) which is invalid in Claude API.

**Fix**: Prefix separator is `_` (underscore). Example: `jira_searchJiraIssuesUsingJql`.

### All MCP tools blocked (0 registered)

**Symptom**: Connect succeeds, tools discovered, but 0 allowed.

**Possible causes**:
1. All tools in blocklist (check `JIRA_BLOCKLIST` in `tools.py`)
2. Policy gate not receiving annotations (check MCP server response)

**Debug**: Check logs at `.clarity/logs/app.jsonl` for `mcp_tools_registered` events.

### Connection timeout on first connect

**Symptom**: Timeout during `/connect-jira` on first use.

**Cause**: `npx mcp-remote` downloads on first run + OAuth browser flow.

**Fix**: `JiraConnection.get_mcp_config()` sets `connect_timeout=60.0` for first-connect overhead. If still timing out, run `npx -y mcp-remote` manually first.

### "npx not found"

**Symptom**: `JiraConnection.is_connected()` returns False.

**Fix**: Install Node.js and ensure `npx` is on PATH. Verify: `npx --version`.

---

## Dependency Graph

```
secrets.py (standalone)

mcp/config.py (standalone)
     |
     v
mcp/client.py ----------> config.py
     |
     v
mcp/adapter.py ----------> config.py, llm.base (deferred), tools.base (deferred)
     |
     v
mcp/bridge.py -----------> tools.base, adapter.py, client.py
     |
     v
mcp/policy.py (standalone)
     |
     v
mcp/registry.py ---------> tools.base, adapter.py, bridge.py, client.py, config.py, policy.py
     |
     v
mcp/manager.py ----------> client.py, config.py, registry.py, tools.base (TYPE_CHECKING)
     |
     v
core/agent.py ------------> manager.py (McpConnectionManager)
ui/app.py ----------------> jira/connection.py, jira/tools.py, mcp/client.py, mcp/registry.py

jira/connection.py -------> mcp/config.py
jira/tools.py ------------> mcp/policy.py
```

**Circular import avoidance**: `adapter.py` defers imports of `ToolDefinition` and `ToolResult` to method bodies to break the chain `adapter -> llm.base -> session -> core -> llm`.
