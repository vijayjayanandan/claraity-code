# MCP Integration Infrastructure

> **One-line summary**: Makes external services (Jira, GitHub, etc.) look like native agent tools. The LLM never knows the difference.

---

## The Big Picture

Think of MCP as a **universal power adapter**. Your agent's toolbox is the wall socket (one standard shape). External services are foreign appliances (each with a different plug). The MCP layer converts every foreign plug into the standard shape so they all just work.

```
                    What the LLM sees
               +--------------------------+
               |  read_file               |
               |  write_file              |
               |  jira_searchIssues  <--------- MCP tool (LLM can't tell)
               |  jira_createIssue   <--------- MCP tool (LLM can't tell)
               |  execute_command         |
               +--------------------------+
                    Flat tool list
```

---

## Architecture

```
                           CodingAgent
                               |
                    McpConnectionManager          Manages all connections
                     /         |         \
              "jira"       "github"      ...      Named connections
                |              |
         McpConnection    McpConnection           Per-server bundle
          |  |  |  |
          |  |  |  +-- McpPolicyGate              Security checkpoint
          |  |  +----- McpToolRegistry            Discovery + registration
          |  +-------- McpBridgeTool(s)           Native-looking wrappers
          +----------- McpClient                  JSON-RPC communication
                           |
                      McpTransport                Wire protocol
                       /        \
                SseTransport  StdioTransport      Remote vs Local
```

### Component Roles

| Component | Analogy | What it does |
|-----------|---------|--------------|
| **McpConnectionManager** | Power strip | Manages multiple connections by name. Handles startup and shutdown for all. |
| **McpClient** | The cable | Speaks JSON-RPC to the MCP server. Handles protocol handshake. |
| **McpTransport** | The wire type | SSE (HTTP for remote servers) or Stdio (subprocess for local proxies). |
| **McpToolRegistry** | Import office | Discovers tools from server, converts them, registers them in the agent. |
| **McpBridgeTool** | Power adapter | Wraps each MCP tool as a native `Tool` subclass. Agent executes it like any other tool. |
| **McpPolicyGate** | Security checkpoint | Reads MCP annotations to decide: allow? require user approval? block? |
| **McpToolAdapter** | Shape converter | Translates between MCP schemas/results and internal `ToolDefinition`/`ToolResult` formats. |
| **SecretStore** | Vault | Stores auth tokens in OS keychain or encrypted file. Tokens never leak to logs. |

### File Map

```
src/integrations/
+-- secrets.py                 SecretStore (keyring + encrypted file)
+-- mcp/
|   +-- manager.py             McpConnectionManager  <-- start here
|   +-- client.py              McpTransport + McpClient
|   +-- registry.py            McpToolRegistry
|   +-- bridge.py              McpBridgeTool
|   +-- policy.py              McpPolicyGate + ToolPolicy
|   +-- adapter.py             McpToolAdapter
|   +-- config.py              McpServerConfig dataclass
+-- jira/
    +-- connection.py          JiraConnection (config + npx command)
    +-- tools.py               Jira blocklist + policy gate factory
```

---

## Data Flow

### 1. Connect (`/connect-jira`)

```
User types /connect-jira
       |
       v
  JiraConnection.get_mcp_config()  -->  McpServerConfig
       |
       v
  McpClient + StdioTransport      -->  Launches: npx mcp-remote <url>
       |
       v
  client.connect()                -->  MCP handshake (initialize + initialized)
       |
       v
  registry.discover_and_register()
       |
       +--  client.list_tools()        Fetch 34 tool schemas from Atlassian
       +--  adapter.adapt_schemas()    Convert to ToolDefinition (add "jira_" prefix)
       +--  policy_gate.register()     Classify each: read-only? write? blocked?
       +--  McpBridgeTool(...)         Create native Tool wrapper per allowed tool
       +--  tool_executor.register()   Now visible to LLM like any native tool
       |
       v
  McpConnection stored as manager._connections["jira"]
```

### 2. Tool Execution

```
LLM returns: {"name": "jira_searchJiraIssuesUsingJql", "arguments": {...}}
       |
       v
  agent.execute_tool()
       |
       v
  ToolExecutor finds "jira_searchJiraIssuesUsingJql"  -->  It's a McpBridgeTool
       |
       v
  McpBridgeTool.execute()
       |
       +--  Dispatches async call to original event loop
       +--  client.invoke("searchJiraIssuesUsingJql", args)  -->  JSON-RPC tools/call
       +--  adapter.adapt_result()                            -->  ToolResult
       |
       v
  ToolResult returned (identical format to native tools)
```

### 3. Disconnect

```
  /disconnect-jira                    Ctrl+Q (exit TUI)
       |                                    |
       v                                    v
  manager.disconnect("jira")          manager.shutdown_sync()
       |                                    |
  Async graceful:                     Sync emergency:
  +-- Unregister bridge tools         +-- For each connection:
  +-- registry.clear()                |   +-- Neutralize asyncio internals
  +-- client.disconnect()             |   +-- Kill subprocess
                                      +-- Clear all connections
```

> **Why two disconnect paths?** The TUI's `on_unmount()` is synchronous and the event loop is shutting down. Async cleanup can't run. `shutdown_sync()` kills subprocesses directly without needing the event loop.

---

## Security Model

```
  Token lifecycle:

  SecretStore ---[get]--> ephemeral token ---[pass]--> Transport
                                                          |
                          NOT stored on McpClient     Injected per-request
                          NOT in logs                 Cleared on disconnect
                          NOT in MessageStore
```

### Tool Approval

```
  MCP server annotations:                    Agent behavior:

  readOnlyHint: true       -- Read-only  --> Auto-approved
  readOnlyHint: false      -- Write      --> User approval required
  destructiveHint: true    -- Dangerous  --> User approval always required
  (no annotations)         -- Unknown    --> User approval required (conservative)
```

Per-integration **blocklist** can permanently block dangerous tools:
```python
# src/integrations/jira/tools.py
JIRA_BLOCKLIST = {"jira_deleteProject"}  # Never exposed to LLM
```

---

## Jira Integration

```
  ClarAIty Agent
       | stdin/stdout (JSON-RPC)
       v
  npx mcp-remote https://mcp.atlassian.com/v1/mcp
       | HTTPS (OAuth 2.1)
       v
  Atlassian Remote MCP Server  -->  Jira Cloud REST API
```

- **First connect**: Browser opens for OAuth consent. Tokens cached by `mcp-remote`.
- **Subsequent connects**: Automatic token reuse.
- **Config**: `.clarity/integrations/jira.json` (no secrets, just cloud URL).
- **Tools**: 34 discovered from Atlassian (search, create, edit issues, manage sprints, etc.)
- **Prerequisites**: Node.js + npm (`npx` on PATH), Atlassian Cloud account.

---

## Adding a New Integration

```
  Step 1                    Step 2                   Step 3
  Create module             Add TUI command          Done - no agent changes

  src/integrations/         app.py:                  McpConnectionManager
    github/                   _connect_github()      handles it automatically
      connection.py             GitHubConnection
      tools.py                  + McpClient
                                + McpToolRegistry
                                + agent.enable_mcp_integration("github", ...)
```

> Deep dive: Follow the pattern in `src/integrations/jira/` and `tests/integrations/test_mcp_manager.py`.

---

## Testing

```bash
pytest tests/integrations/ -v          # All 83 tests
pytest tests/integrations/test_mcp_manager.py -v   # Specific module
```

| Test File | Count | What's Tested |
|-----------|-------|---------------|
| `test_mcp_adapter.py` | 17 | Schema translation, result truncation, prefix handling |
| `test_mcp_policy.py` | 17 | Annotation-based policy, blocklist, Jira factory |
| `test_mcp_bridge.py` | 13 | Bridge execution, event loop handling, error paths |
| `test_mcp_manager.py` | 18 | Connect/disconnect, shutdown, tool routing, transport cleanup |
| `test_secrets.py` | 18 | Encrypted storage, keyring, leak prevention |

> All tests use mock transports (`AsyncMock(spec=McpTransport)`) -- no real subprocesses. See `tests/integrations/conftest.py` for shared fixtures.

---

## Troubleshooting

| Symptom | Cause | Fix |
|---------|-------|-----|
| `RuntimeError: Event loop is closed` on exit | asyncio transport `__del__` fires after loop closes | Fixed: `close_sync()` neutralizes transport internals |
| `readuntil() called while another coroutine is already waiting` | Orphaned coroutine from timeout still holds `stdout.readline()` | Fixed: `future.cancel()` on timeout + `asyncio.Lock` on send |
| Tool name pattern error `'^[a-zA-Z0-9_-]{1,128}$'` | Prefix separator was `.` (invalid) | Fixed: separator is `_` (e.g. `jira_searchIssues`) |
| 0 tools registered after connect | All tools in blocklist, or server missing annotations | Check `JIRA_BLOCKLIST` and logs for `mcp_tools_registered` |
| Timeout on first `/connect-jira` | `npx mcp-remote` downloads + OAuth browser flow | `connect_timeout=60.0`; or run `npx -y mcp-remote` manually first |
| `npx not found` | Node.js not installed | Install Node.js, verify: `npx --version` |

---

## Deep Dive Pointers

Read these files in order when you need to understand or modify the MCP layer:

1. **`manager.py`** -- Start here. Overall lifecycle and multi-connection management.
2. **`client.py`** -- Transport implementations, MCP protocol handshake, subprocess cleanup.
3. **`registry.py`** -- Discovery pipeline, caching, tool registration.
4. **`bridge.py`** -- Event loop bridging (async-in-sync-in-async), timeout handling.
5. **`policy.py`** -- Annotation parsing, policy derivation, blocklist.
6. **`adapter.py`** -- Schema translation, result normalization, truncation.
7. **`secrets.py`** -- Keyring vs encrypted file, token lifecycle.

### Import Dependencies

```
config.py (standalone)          secrets.py (standalone)
    |
    v
client.py --> config
    |
    v
adapter.py --> config (defers llm.base, tools.base to avoid circular imports)
    |
    v
policy.py (standalone)
    |
    v
bridge.py --> tools.base, adapter, client
    |
    v
registry.py --> tools.base, adapter, bridge, client, config, policy
    |
    v
manager.py --> client, config, registry
```
