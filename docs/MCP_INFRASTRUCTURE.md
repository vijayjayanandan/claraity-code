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
               |  jira_search        <--------- MCP tool (LLM can't tell)
               |  jira_get_issue     <--------- MCP tool (LLM can't tell)
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
|   +-- client.py              McpTransport + McpClient (+ stderr drain)
|   +-- registry.py            McpToolRegistry
|   +-- bridge.py              McpBridgeTool
|   +-- policy.py              McpPolicyGate + ToolPolicy
|   +-- adapter.py             McpToolAdapter
|   +-- config.py              McpServerConfig dataclass
+-- jira/
    +-- connection.py          JiraConnection (profiles + uvx command)
    +-- tools.py               Jira blocklist + policy gate factory

src/ui/
+-- jira_config_screen.py      TUI modal for Jira profile configuration
```

---

## Data Flow

### 1. Connect (`/connect-jira [profile]`)

```
User types /connect-jira corporate
       |
       v
  Auto-disconnect existing Jira connection (if any)
       |
       v
  JiraConnection("corporate").get_mcp_config()  -->  McpServerConfig
       |                                              (extra_env: JIRA_URL,
       |                                               JIRA_USERNAME, JIRA_API_TOKEN)
       v
  McpClient + StdioTransport  -->  Launches: uvx mcp-atlassian
       |                           (env vars pass credentials to subprocess)
       v
  client.connect()             -->  MCP handshake (initialize + initialized)
       |                           (stderr drained in background to prevent deadlock)
       v
  registry.discover_and_register()
       |
       +--  client.list_tools()        Fetch 32 tool schemas from mcp-atlassian
       +--  adapter.adapt_schemas()    Convert to ToolDefinition (no prefix added;
       |                               mcp-atlassian already names tools jira_*)
       +--  policy_gate.register()     Classify each: read-only? write? blocked?
       +--  McpBridgeTool(...)         Create native Tool wrapper per allowed tool
       +--  tool_executor.register()   Now visible to LLM like any native tool
       |
       v
  McpConnection stored as manager._connections["jira"]
```

### 2. Tool Execution

```
LLM returns: {"name": "jira_search", "arguments": {"jql": "project = CC"}}
       |
       v
  agent.execute_tool()
       |
       v
  ToolExecutor finds "jira_search"  -->  It's a McpBridgeTool
       |
       v
  McpBridgeTool.execute()
       |
       +--  Dispatches async call to original event loop
       +--  client.invoke("jira_search", args)  -->  JSON-RPC tools/call
       +--  adapter.adapt_result()               -->  ToolResult
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
  +-- Cancel stderr drain task        +-- For each connection:
  +-- Unregister bridge tools         |   +-- Cancel stderr drain task
  +-- registry.clear()               |   +-- Neutralize asyncio internals
  +-- client.disconnect()             |   +-- Kill subprocess
                                      +-- Clear all connections
```

> **Why two disconnect paths?** The TUI's `on_unmount()` is synchronous and the event loop is shutting down. Async cleanup can't run. `shutdown_sync()` kills subprocesses directly without needing the event loop.

---

## Security Model

```
  API token lifecycle:

  User configures via /config-jira
       |
       v
  SecretStore.set("jira_api_token_<profile>", token)
       |                                                   At connect time:
       v                                                         |
  Config JSON (.clarity/integrations/jira/<profile>.json)        v
  Contains ONLY: jira_url, username, enabled              SecretStore.get()
  NEVER contains: api_token                                      |
                                                                 v
                                                          extra_env dict
                                                                 |
                                                                 v
                                                          Subprocess env vars
                                                          (JIRA_API_TOKEN)
```

**Key invariant**: API tokens are stored only in SecretStore (OS keychain or AES-256 encrypted file). They never appear in config JSON, logs, or JSONL session files.

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
  uvx mcp-atlassian             (sooperset/mcp-atlassian Python MCP server)
       | API token auth          (env vars: JIRA_URL, JIRA_USERNAME, JIRA_API_TOKEN)
       v
  Jira Cloud REST API
```

- **Auth method**: API token (from id.atlassian.com), stored in SecretStore.
- **Profiles**: Multiple named profiles (e.g. "personal", "corporate") for different Jira instances.
- **Config dir**: `.clarity/integrations/jira/<profile>.json` (no secrets, just URL + username + enabled).
- **TUI config**: Command palette "Configure Jira" or `/config-jira` opens a modal with profile management, connection status, and disconnect.
- **Tools**: 32 discovered from mcp-atlassian (search, get/create/edit issues, manage sprints, etc.)
- **Auto-reconnect**: Connecting to a different profile auto-disconnects the current one.
- **Prerequisites**: Python + uv (`uvx` on PATH), Jira Cloud account + API token.

### Slash Commands

| Command | Action |
|---------|--------|
| `/config-jira` | Open Jira configuration modal (profiles, credentials, connect/disconnect) |
| `/connect-jira` | Connect to Jira (auto-selects if one profile, lists if multiple) |
| `/connect-jira corporate` | Connect to a specific named profile |
| `/disconnect-jira` | Disconnect from Jira |

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
  src/ui/                       + agent.enable_mcp_integration("github", ...)
    github_config_screen.py
```

> Deep dive: Follow the pattern in `src/integrations/jira/` and `src/ui/jira_config_screen.py`. See `tests/integrations/test_jira_connection.py` for test patterns.

---

## Testing

```bash
pytest tests/integrations/ -v          # All 112 tests
pytest tests/integrations/test_mcp_manager.py -v   # Specific module
```

| Test File | Count | What's Tested |
|-----------|-------|---------------|
| `test_jira_connection.py` | 29 | Profile CRUD, SecretStore isolation, config persistence, MCP config generation |
| `test_mcp_adapter.py` | 17 | Schema translation, result truncation, prefix handling |
| `test_mcp_policy.py` | 17 | Annotation-based policy, blocklist, Jira factory |
| `test_mcp_bridge.py` | 13 | Bridge execution, event loop handling, error paths |
| `test_mcp_manager.py` | 18 | Connect/disconnect, shutdown, tool routing, transport cleanup |
| `test_secrets.py` | 18 | Encrypted storage, keyring, leak prevention |

> MCP tests use mock transports (`AsyncMock(spec=McpTransport)`) -- no real subprocesses. Jira connection tests use `FakeSecretStore` for isolation. See `tests/integrations/conftest.py` for shared fixtures.

---

## Troubleshooting

| Symptom | Cause | Fix |
|---------|-------|-----|
| `RuntimeError: Event loop is closed` on exit | asyncio transport `__del__` fires after loop closes | Fixed: `close_sync()` neutralizes transport internals |
| TUI hangs at "Connecting to Jira..." | MCP server stderr fills OS pipe buffer (64KB), deadlocking the subprocess | Fixed: `StdioTransport` drains stderr in background task |
| `MCP connection 'jira' already exists` | Connecting without disconnecting first | Fixed: `_connect_jira` auto-disconnects before reconnecting |
| Double tool prefix (`jira_jira_search`) | `tool_prefix` set when server already prefixes names | Fixed: `tool_prefix=""` for mcp-atlassian (server provides `jira_` prefix) |
| `readuntil() called while another coroutine is already waiting` | Orphaned coroutine from timeout still holds `stdout.readline()` | Fixed: `future.cancel()` on timeout + `asyncio.Lock` on send |
| Tool name pattern error `'^[a-zA-Z0-9_-]{1,128}$'` | Prefix separator was `.` (invalid) | Fixed: separator is `_` (e.g. `jira_search`) |
| 0 tools registered after connect | All tools in blocklist, or server missing annotations | Check `JIRA_BLOCKLIST` and logs for `mcp_tools_registered` |
| Connection timeout (120s) | `uvx mcp-atlassian` first-time install is slow | Re-run; or pre-install: `uvx mcp-atlassian --help` |
| `uvx not found` | uv not installed | Install uv: `powershell -c "irm https://astral.sh/uv/install.ps1 \| iex"` |
| SSL errors connecting to Jira behind Zscaler | Corporate proxy with custom root CA | Add Zscaler Root CA to mcp-atlassian's certifi cacert.pem |

---

## Deep Dive Pointers

Read these files in order when you need to understand or modify the MCP layer:

1. **`manager.py`** -- Start here. Overall lifecycle and multi-connection management.
2. **`client.py`** -- Transport implementations, MCP protocol handshake, stderr drain, subprocess cleanup.
3. **`registry.py`** -- Discovery pipeline, caching, tool registration.
4. **`bridge.py`** -- Event loop bridging (async-in-sync-in-async), timeout handling.
5. **`policy.py`** -- Annotation parsing, policy derivation, blocklist.
6. **`adapter.py`** -- Schema translation, result normalization, truncation.
7. **`secrets.py`** -- Keyring vs encrypted file, token lifecycle.
8. **`connection.py`** -- Jira profile management, SecretStore integration, McpServerConfig generation.

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

jira/connection.py --> mcp.config, secrets (lazy)
jira/tools.py --> mcp.policy
```
