# ClarAIty Code

An AI-powered coding agent with a Textual TUI, VS Code extension, 30+ built-in tools, subagent delegation, and multi-LLM support. Built entirely from scratch in Python + TypeScript -- no LangChain, no AutoGen, no frameworks.

**~86K lines of Python | ~6K lines of TypeScript/React | 227 source files | 20 modules**

---

## Architecture

```mermaid
graph TB
    subgraph VS_Code["VS Code Extension"]
        WV["React Webview<br/><i>22 components, useReducer state machine</i>"]
        EH["Extension Host<br/><i>sidebar-provider, CodeLens, undo, diff editor</i>"]
        WV <-->|postMessage| EH
    end

    subgraph Transport["Stdio Transport"]
        STDIN["stdin pipe<br/><i>JSON-RPC commands</i>"]
        TCP["TCP socket<br/><i>Event stream</i>"]
        EH -->|"ClientMessage"| STDIN
        TCP -->|"ServerMessage"| EH
    end

    subgraph Server["Python Server"]
        STDIO["StdioProtocol<br/><i>Message dispatch, config, sessions</i>"]
        SER["Serializers<br/><i>UIEvent &harr; JSON</i>"]
        SAB["SubagentBridge<br/><i>Event relay</i>"]
        STDIN --> STDIO
        STDIO --> TCP
        STDIO --- SER
        STDIO --- SAB
    end

    subgraph Core["Agent Core"]
        AGT["CodingAgent<br/><i>stream_response() &mdash; single async entry point</i>"]
        TG["ToolGatingService<br/><i>4-layer: repeat &rarr; plan &rarr; director &rarr; approval</i>"]
        STH["SpecialToolHandlers<br/><i>clarify, plan approval, director</i>"]
        CB["ContextBuilder<br/><i>Token-budgeted assembly</i>"]
        ER["ErrorRecovery<br/><i>SHA256 repeat detection, retry budgets</i>"]
        AGT --> TG
        AGT --> STH
        AGT --> CB
        AGT --> ER
    end

    subgraph Tools["Tool System"]
        TE["ToolExecutor<br/><i>30+ tools, parallel execution</i>"]
        FO["File Ops<br/><i>read/write/edit/append</i>"]
        SR["Search<br/><i>grep, glob, AST, LSP</i>"]
        DEL["Delegation<br/><i>Subprocess IPC</i>"]
        MCP["MCP<br/><i>External tools</i>"]
        TE --> FO
        TE --> SR
        TE --> DEL
        TE --> MCP
    end

    subgraph LLM["LLM Backend"]
        BASE["LLMBackend ABC<br/><i>ProviderDelta streaming contract</i>"]
        OAI["OpenAI<br/><i>GPT, Azure, Groq, DashScope</i>"]
        ANT["Anthropic<br/><i>Claude + prompt caching</i>"]
        OLL["Ollama<br/><i>Local models</i>"]
        BASE --> OAI
        BASE --> ANT
        BASE --> OLL
    end

    subgraph Memory["Memory & Context"]
        MM["MemoryManager<br/><i>Single writer</i>"]
        WM["WorkingMemory<br/><i>Recent context + compaction</i>"]
        EM["EpisodicMemory<br/><i>Compressed history</i>"]
        MM --> WM
        MM --> EM
    end

    subgraph Persistence["Persistence"]
        MS["MessageStore<br/><i>In-memory projection + indexes</i>"]
        SW["SessionWriter<br/><i>Async JSONL append</i>"]
        JSONL[("session.jsonl<br/><i>Append-only ledger</i>")]
        MS --> SW --> JSONL
    end

    subgraph Observability["Observability"]
        LOG["structlog<br/><i>JSONL + SQLite</i>"]
        MET["ErrorStore<br/><i>metrics.db</i>"]
        TL["TranscriptLogger<br/><i>Session replay</i>"]
    end

    STDIO <--> AGT
    AGT --> TE
    AGT --> BASE
    AGT --> MM
    MM --> MS
    DEL -.->|"subprocess"| SAB
```

### Key Design Decisions

- **Streaming-first**: LLM responses stream through every layer to the UI. Nothing is buffered end-to-end.
- **Single writer persistence**: Only `MemoryManager` writes to `MessageStore`. The TUI and VS Code read via subscriptions.
- **Protocol-agnostic core**: The agent yields `UIEvent` objects and accepts `UserAction` inputs through an abstract protocol. It knows nothing about transport.
- **4-layer tool gating**: Repeat detection (SHA256) -> Plan mode gate -> Director gate -> Human approval. Composable, not monolithic.
- **Budget-aware context**: Token counting at every stage with GREEN/YELLOW/ORANGE/RED pressure thresholds that trigger compaction.
- **Subagent isolation**: Each subagent runs in its own subprocess with independent context, LLM config, and message store.

---

## Module Map

```
src/
├── core/               # Agent orchestrator, tool gating, streaming, error recovery
├── llm/                # LLM backends (OpenAI, Anthropic, Ollama), retry, credentials
├── tools/              # 30+ tools: file ops, search, git, web, delegation, planning
├── memory/             # Working memory, episodic memory, compaction, context injection
├── session/            # Message store, JSONL persistence, session resume
├── ui/                 # Textual TUI (3300-line app), widgets, store adapter
├── server/             # Stdio + WebSocket servers, JSON-RPC, event serialization
├── subagents/          # Subprocess-based specialist agents with IPC
├── director/           # Multi-phase task orchestration
├── prompts/            # System prompts, enrichment, templates
├── observability/      # Structured JSONL logging, SQLite metrics, transcript logger
├── code_intelligence/  # LSP client, AST analysis, symbol resolution
├── integrations/       # Jira, MCP (Model Context Protocol)
├── hooks/              # Lifecycle hooks (pre/post tool execution)
├── security/           # File permission validation, path sandboxing
├── platform/           # Windows-specific adaptations
└── claraity/           # Knowledge DB + Beads task tracker (2 SQLite DBs)

claraity-vscode/        # VS Code extension
├── src/                # Extension host (TS): sidebar provider, stdio transport, CodeLens
└── webview-ui/         # React webview: 22 components, central reducer state machine
```

---

## Core Data Flow

### User Message to Agent Response

```mermaid
sequenceDiagram
    participant UI as VS Code / TUI
    participant SP as StdioProtocol
    participant AG as CodingAgent
    participant CB as ContextBuilder
    participant LLM as LLM Backend
    participant MM as MemoryManager
    participant MS as MessageStore

    UI->>SP: chat_message (JSON-RPC via stdin)
    SP->>AG: stream_response(user_input, attachments)
    AG->>MM: add_user_message()
    MM->>MS: store message
    AG->>CB: build_context() [token budgeting]
    AG->>LLM: astream(messages, tools)

    loop Streaming Response
        LLM-->>AG: ProviderDelta (text / thinking / tool_calls)
        AG-->>SP: yield UIEvent (TextDelta, ThinkingDelta, ...)
        SP-->>UI: TCP event stream
    end

    Note over AG: Tool calls detected?

    loop Tool Execution Loop
        AG->>AG: ToolGatingService.evaluate()<br/>repeat → plan → director → approval
        alt Needs Approval
            AG-->>UI: ToolCallStart (awaiting_approval)
            UI->>AG: ApprovalResult (approved/rejected)
        end
        AG->>AG: ToolExecutor.execute() [parallel where possible]
        AG->>MM: add_assistant_message() + tool_results
        MM->>MS: store messages
        MS-->>MS: SessionWriter → JSONL append
        AG->>LLM: astream(messages, tools) [next iteration]
        LLM-->>AG: ProviderDelta
        AG-->>SP: yield UIEvents
        SP-->>UI: TCP event stream
    end

    AG-->>SP: yield StreamEnd
    SP-->>UI: stream_end
```

### Subagent Lifecycle

```mermaid
sequenceDiagram
    participant AG as Main Agent
    participant DT as DelegationTool
    participant RP as Runner (subprocess)
    participant SA as SubAgent
    participant BR as SubagentBridge
    participant UI as VS Code / TUI

    AG->>DT: delegate_to_subagent("code-reviewer", task)
    DT->>RP: spawn subprocess, stdin: config JSON
    RP->>SA: create SubAgent (own LLM, MessageStore, tools)
    RP-->>DT: stdout: {event: "registered", subagent_id}
    DT->>BR: bridge.register(subagent_id)
    BR-->>UI: subagent registered

    loop Subagent Execution
        SA->>SA: stream_response() → tool calls → results
        RP-->>DT: stdout: {event: "notification", tool_state/message}
        DT->>BR: bridge.push_notification()
        BR-->>UI: tool_state_updated / message_added
    end

    RP-->>DT: stdout: {event: "done", result}
    DT->>BR: bridge.unregister(subagent_id)
    BR-->>UI: subagent unregistered
    DT-->>AG: return ToolResult
```

---

## Tools (30+)

| Category | Tools |
|----------|-------|
| **File Operations** | `read_file`, `write_file`, `edit_file`, `append_to_file`, `list_directory` |
| **Code Search** | `search_code`, `grep`, `glob`, `analyze_code`, `get_file_outline`, `get_symbol_context` |
| **Git** | `git_status`, `git_diff` |
| **Web** | `web_search`, `web_fetch` |
| **Execution** | `run_command` (with command safety analysis) |
| **Planning** | `enter_plan_mode`, `request_plan_approval` |
| **Delegation** | `delegate_to_subagent` (8 specialist types) |
| **Knowledge** | `knowledge_query`, `knowledge_update` |
| **Other** | `create_checkpoint`, `clarify` |

---

## Subagents

Specialist agents that run as isolated subprocesses, each with their own context window and configurable LLM:

| Agent | Purpose |
|-------|---------|
| **code-reviewer** | Code quality, security, performance analysis |
| **test-writer** | Comprehensive test suite generation |
| **doc-writer** | Technical documentation |
| **code-writer** | Focused implementation (no exploration) |
| **explore** | Read-only codebase navigation |
| **planner** | Step-by-step implementation plans |
| **general-purpose** | Full tool access for multi-step tasks |
| **knowledge-builder** | Autonomous knowledge base generation |

---

## LLM Support

Works with any OpenAI-compatible API. Three native backends:

| Backend | Providers |
|---------|-----------|
| **OpenAI** | GPT-4o, GPT-4.1, o3, Azure OpenAI, Groq, DashScope, Together.ai |
| **Anthropic** | Claude Sonnet, Opus, Haiku -- with native prompt caching |
| **Ollama** | Any local model (Qwen, DeepSeek, Llama, Mistral, etc.) |

Features: automatic prompt caching (50-80% cost reduction on long sessions), exponential backoff with jitter, credential store (OS keyring + env fallback), hot-swap model config without restart.

---

## VS Code Extension

Full-featured sidebar with:

- **Chat interface** with streaming markdown, syntax highlighting, image paste
- **Tool cards** with live status, approve/reject buttons, inline diff viewer
- **Subagent cards** with nested tool execution visibility
- **Interactive widgets**: clarify questions, plan approval, pause prompts
- **CodeLens**: Accept/Reject/View Diff on agent-modified files
- **File decorations**: "AI" badge on modified files
- **Undo manager**: Per-turn file snapshot checkpoints (max 10)
- **Config panel**: LLM backend, model, temperature, subagent overrides
- **Session management**: List, resume, and replay past sessions

Transport: stdin (JSON-RPC commands) + TCP socket (event stream). TCP used instead of stdout due to a Windows libuv pipe reliability issue.

---

## Observability

- **Structured logging**: `structlog` -> async queue -> JSONL file + SQLite (no console output)
- **Metrics DB**: `.claraity/metrics.db` -- error taxonomy, performance tracking
- **Transcript logger**: Full conversation replay with head/tail preservation
- **Context propagation**: `ContextVar`-based run_id, session_id, stream_id across async boundaries
- **Automatic redaction**: API keys, tokens, database URIs stripped from logs

```bash
python -m src.observability.log_query --tail 50
```

---

## Permission Modes

| Mode | Behavior | Toggle |
|------|----------|--------|
| **Normal** | Asks approval for write/execute operations | `/mode n` or `Alt+M` |
| **Auto** | Executes all tools without asking | `/mode a` |
| **Plan** | Read-only -- write operations blocked entirely | `/mode p` |

---

## Setup

### From Source

```bash
git clone <repo-url>
cd ai-coding-agent
pip install -e ".[dev]"
```

Requires **Python 3.10+**.

### LLM Configuration

Set via environment variables or `.claraity/config.yaml`:

```bash
export LLM_API_KEY=your-key
export LLM_BASE_URL=https://api.openai.com/v1
export LLM_MODEL=gpt-4o
```

Or for local models:

```bash
ollama pull qwen2.5-coder:7b
export LLM_BACKEND_TYPE=ollama
export LLM_MODEL=qwen2.5-coder:7b
```

### Run

```bash
python -m src.cli
```

### VS Code Extension

```bash
cd claraity-vscode
npm install && npm run build
# Install the .vsix from claraity-vscode/ directory
```

---

## Configuration

All configuration in `.claraity/config.yaml`:

```yaml
llm:
  backend_type: openai
  base_url: https://api.openai.com/v1
  model: gpt-4o
  context_window: 128000
  temperature: 0.2
  max_tokens: 16384

  subagents:
    code-reviewer:
      model: claude-sonnet-4-5-20250929
    test-writer:
      model: claude-sonnet-4-5-20250929

mcp_servers:
  - name: jira
    server_url: http://localhost:3000/sse
    tool_prefix: jira_
```

---

## Project Structure

```
.claraity/                  # Project-level config and data
  config.yaml               # LLM, logging, MCP configuration
  sessions/                 # JSONL session files
    subagents/              # Subagent transcripts
  logs/app.jsonl            # Structured application logs
  metrics.db                # SQLite metrics and error tracking
  knowledge/                # Project knowledge files (loaded at startup)
  memory.md                 # Project-level memory (team-shareable)
```

---

## Testing

```bash
pytest tests/                                    # All tests
pytest tests/tools/test_file_operations.py -v    # Specific file
pytest -m "not integration"                      # Skip integration tests
```

---

## License

MIT License. See [LICENSE](LICENSE) for details.
