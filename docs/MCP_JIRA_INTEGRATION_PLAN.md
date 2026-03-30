# MCP + Jira Integration Plan

## Context

ClarAIty currently has a native tool system: `Tool` base class + `ToolExecutor` registry + static `ALL_TOOLS` list of `ToolDefinition` schemas passed to the LLM on every call. We want to add MCP (Model Context Protocol) tool support so external services like Atlassian Jira can be discovered dynamically and invoked through the same tool execution path the LLM already uses.

**Key design decision**: MCP tools must be indistinguishable from native tools from the LLM's perspective. Both types share the same `ToolDefinition` schema format, the same `ToolResult` return type, and the same JSONL persistence path. The only differences are: (a) MCP tools are discovered at runtime, (b) they go through a policy gate, and (c) their execution proxies to the MCP server instead of local Python code.

---

## Architecture

```
                  ┌──────────────────┐
                  │    ALL_TOOLS      │ Static native tool schemas
                  └────────┬─────────┘
                           │
                  ┌────────▼─────────┐
                  │  ToolRegistry     │ Merges native + MCP tools
                  │  (new, thin)      │ Returns List[ToolDefinition]
                  └────────┬─────────┘
                           │
           ┌───────────────┼───────────────┐
           │                               │
   ┌───────▼───────┐             ┌─────────▼─────────┐
   │ Native Tools   │             │  MCP Tools         │
   │ (ToolExecutor) │             │  (McpBridge)       │
   └───────────────┘             └─────────┬──────────┘
                                           │
                              ┌────────────▼────────────┐
                              │    McpPolicyGate         │
                              │ (allowlist + read/write) │
                              └────────────┬────────────┘
                                           │
                              ┌────────────▼────────────┐
                              │    McpClient             │
                              │ (SSE transport → Rovo)   │
                              └────────────┬────────────┘
                                           │
                              ┌────────────▼────────────┐
                              │    SecretStore           │
                              │ (keyring or AES-local)   │
                              └─────────────────────────┘
```

---

## Files to Create

| File | Purpose |
|------|---------|
| `src/integrations/__init__.py` | Package init |
| `src/integrations/mcp/__init__.py` | MCP package init |
| `src/integrations/mcp/client.py` | `McpClient` - SSE/stdio transport, list_tools, invoke |
| `src/integrations/mcp/adapter.py` | `McpToolAdapter` - MCP schema → `ToolDefinition` + `ToolResult` normalization |
| `src/integrations/mcp/policy.py` | `McpPolicyGate` - allowlist, read/write classification, approval requirement |
| `src/integrations/mcp/registry.py` | `McpToolRegistry` - merges native + MCP tools, session-scoped |
| `src/integrations/mcp/bridge.py` | `McpBridge` - `Tool` subclass that proxies execute() to McpClient |
| `src/integrations/mcp/config.py` | MCP server config dataclass |
| `src/integrations/secrets.py` | `SecretStore` interface + keyring/AES-file backends |
| `src/integrations/jira/__init__.py` | Jira integration package |
| `src/integrations/jira/connection.py` | Jira connection flow (OAuth URL, token exchange, test) |
| `src/integrations/jira/tools.py` | Jira MVP tool allowlist + descriptions |
| `tests/integrations/__init__.py` | Test package |
| `tests/integrations/test_mcp_adapter.py` | Schema discovery + registration tests |
| `tests/integrations/test_mcp_policy.py` | Policy gate tests (allowlist, write approval) |
| `tests/integrations/test_mcp_bridge.py` | End-to-end mock MCP invoke + JSONL persistence |
| `tests/integrations/test_secrets.py` | Secret store tests + no-leak grep |

## Files to Modify

| File | Change |
|------|--------|
| `src/tools/tool_schemas.py` | Add `get_all_tools(mcp_tools=[])` function that merges native + MCP |
| `src/core/agent.py` | In `_register_tools()`: initialize McpToolRegistry, register MCP bridge tools. In `stream_response()` / `_execute_with_tools*()`: use `get_all_tools()` instead of bare `ALL_TOOLS`. In `needs_approval()`: check McpPolicyGate for MCP write tools. |
| `src/tools/base.py` | Add `TOOL_TIMEOUT_OVERRIDES` entries for MCP tools (60s default) |

---

## Implementation Steps (PR-sized)

### Step 1: SecretStore abstraction (`src/integrations/secrets.py`)
- `SecretStore` protocol with `get(key)`, `set(key, value)`, `delete(key)`, `has(key)`
- `KeyringSecretStore` - uses `keyring` library (OS keychain)
- `EncryptedFileSecretStore` - AES-256 fallback using `cryptography` (Fernet), master key from env var
- `get_secret_store()` factory: tries keyring first, falls back to file
- Secret values are **never** logged, serialized to JSONL, or included in ToolResult output

### Step 2: MCP Client (`src/integrations/mcp/client.py`)
- `McpClient` class with:
  - `connect(server_url, auth_headers)` - establish SSE transport
  - `list_tools()` → returns raw MCP tool schemas (JSON)
  - `invoke(tool_name, arguments)` → returns MCP tool result (JSON)
  - `disconnect()` - cleanup
- Uses `httpx` for SSE (already a transitive dep via `openai`), or `httpx-sse` for streaming
- Auth headers built from SecretStore tokens at connect time
- Connection pooling + retry with exponential backoff
- Mock-friendly: constructor accepts transport interface

### Step 3: MCP Tool Adapter (`src/integrations/mcp/adapter.py`)
- `McpToolAdapter`:
  - `adapt_schema(mcp_tool_json) → ToolDefinition` - translates MCP inputSchema → OpenAI function parameters
  - `adapt_result(mcp_result_json) → ToolResult` - normalizes MCP content blocks → structured JSON string
  - Truncation: if result content > 8KB, truncate with `[truncated, {n} chars total]`
  - Prefix tool names with provider namespace: `jira.search_issues` (not just `search_issues`)

### Step 4: MCP Policy Gate (`src/integrations/mcp/policy.py`)
- `McpPolicyGate`:
  - `ALLOWLIST: Dict[str, ToolPolicy]` - tool name → {allowed: bool, requires_approval: bool}
  - `is_allowed(tool_name) → bool`
  - `requires_approval(tool_name) → bool`
  - Default: block everything not in allowlist
  - Jira MVP allowlist:
    - `jira.search_issues` → read, auto-run
    - `jira.get_issue` → read, auto-run
    - `jira.list_projects` → read, auto-run
    - `jira.create_issue` → write, approval required
    - `jira.add_comment` → write, approval required

### Step 5: MCP Bridge Tool (`src/integrations/mcp/bridge.py`)
- `McpBridgeTool(Tool)`:
  - Constructor takes `McpClient`, tool_name, adapted `ToolDefinition`
  - `execute(**kwargs) → ToolResult` - calls `client.invoke()`, uses adapter to normalize result
  - `_get_parameters()` - returns the adapted parameter schema
  - This makes MCP tools executable through the existing `ToolExecutor`

### Step 6: MCP Tool Registry (`src/integrations/mcp/registry.py`)
- `McpToolRegistry`:
  - `discover_and_register(client, policy_gate, tool_executor)` - calls client.list_tools(), filters through policy gate, adapts schemas, creates McpBridgeTools, registers in ToolExecutor
  - `get_tool_definitions() → List[ToolDefinition]` - returns adapted schemas for LLM
  - `is_mcp_tool(tool_name) → bool` - check if a tool came from MCP
  - In-memory cache with TTL (default 1h). Discovery runs once at startup or on first Jira enablement.
  - `enabled: bool` property - only expose MCP tools when integration is authenticated

### Step 7: Jira Connection Flow (`src/integrations/jira/`)
- `JiraConnection`:
  - `configure(cloud_url)` - store Jira Cloud base URL
  - `authenticate()` - generate OAuth 2.0 authorization URL, handle callback, store tokens via SecretStore
  - `test_connection() → bool` - make a simple API call to verify tokens work
  - `get_mcp_server_url() → str` - construct the Atlassian Rovo MCP endpoint URL
  - `is_connected() → bool` - check if valid tokens exist
- Config persisted to `.claraity/integrations/jira.json` (no secrets, just cloud_url + enabled flag)

### Step 8: Agent Integration
- **`src/tools/tool_schemas.py`**: Add `get_all_tools(mcp_definitions=None)` that returns `ALL_TOOLS + (mcp_definitions or [])`
- **`src/core/agent.py`**:
  - In `__init__`: create `McpToolRegistry` (lazy, no connection yet)
  - In `_register_tools()`: if Jira enabled, call `mcp_registry.discover_and_register()`
  - Replace all `tools=ALL_TOOLS` with `tools=self._get_tools()` where `_get_tools()` calls `get_all_tools(self.mcp_registry.get_tool_definitions())`
  - In `needs_approval()`: add `if self.mcp_registry.is_mcp_tool(tool_name): return self.mcp_registry.policy_gate.requires_approval(tool_name)`

### Step 9: Tests
- **test_mcp_adapter.py**: Verify MCP schema → ToolDefinition conversion, result normalization, truncation
- **test_mcp_policy.py**: Allowlisted tools pass, non-allowlisted blocked, write tools flagged
- **test_mcp_bridge.py**: Mock McpClient, invoke tool, verify ToolResult structure and JSONL content
- **test_secrets.py**: Store/retrieve/delete secrets; grep JSONL + logs for leaked values

---

## Key Design Decisions

1. **MCP tools as `Tool` subclass**: McpBridgeTool extends `Tool`, so it registers in `ToolExecutor` identically to native tools. No special-casing in the execution path.

2. **Namespace prefixing**: MCP tools get prefixed (`jira.search_issues`) to avoid name collisions with native tools and to make the source obvious in logs/JSONL.

3. **Static `ALL_TOOLS` untouched**: We don't mutate the global list. Instead, `_get_tools()` merges at call time. This is safe for subagents that filter `ALL_TOOLS` independently.

4. **Policy gate is separate from approval**: The policy gate controls which MCP tools are even visible to the LLM. The approval system (via `needs_approval()`) controls whether a visible tool requires user confirmation before execution. Both layers apply.

5. **No UI changes**: MCP tool calls persist to JSONL identically to native tools. The TUI renders them from MessageStore using existing tool card widgets. The `meta.extra` field can carry `{"source": "mcp", "provider": "jira"}` for future UI differentiation.

6. **Secrets never in ToolResult**: The McpBridgeTool strips any auth headers before returning results. The SecretStore is never accessed during serialization paths.

---

## Verification

1. **Unit tests**: `pytest tests/integrations/ -v`
2. **Manual smoke test**:
   - Set env vars for Jira Cloud credentials
   - Run `python -m src.cli --tui`
   - Type "search for open bugs in PROJECT" → agent should use `jira.search_issues`
   - Type "create a bug ticket for X" → agent should request approval before `jira.create_issue`
3. **Secret leak check**: `grep -r "Bearer\|api_token\|access_token" .claraity/sessions/ .claraity/logs/` should return nothing
4. **JSONL replay**: Stop and restart with `--session` flag → Jira tool results should render from JSONL without live Jira connection
