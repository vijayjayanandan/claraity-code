# ClarAIty Code

An AI-powered coding agent with a professional TUI, 30+ built-in tools, subagent delegation, and multi-LLM support. Works with Claude, GPT, Qwen, DeepSeek, Ollama, and any OpenAI-compatible API.

## Quick Start

```bash
pip install claraity-code
```

Set your LLM endpoint in `.clarity/config.yaml` (or environment variables):

```bash
export LLM_API_KEY=your-api-key
export LLM_BASE_URL=https://api.openai.com/v1
export LLM_MODEL=gpt-4o
```

Launch the TUI:

```bash
claraity --tui
```

Or use simple chat mode:

```bash
claraity
```

## Core Features

### Professional TUI Interface

Built on [Textual](https://textual.textualize.io/) with streaming responses, syntax-highlighted code blocks, collapsible tool-call cards, and real-time progress indicators. Falls back to a Rich-based CLI for headless environments.

### 30+ Built-in Tools

| Category | Tools | Description |
|----------|-------|-------------|
| **File Operations** | `read_file`, `write_file`, `edit_file`, `append_to_file`, `list_directory` | Stream with line ranges, create, edit, append |
| **Code Search** | `search_code`, `grep`, `glob`, `analyze_code`, `get_file_outline`, `get_symbol_context` | Regex, glob patterns, AST parsing, LSP-based outlines |
| **Git** | `git_status`, `git_diff` | Status, diffs |
| **Web** | `web_search`, `web_fetch` | Search the web, fetch and extract URL content |
| **Execution** | `run_command` | Shell command execution with approval gating |
| **Planning** | `enter_plan_mode`, `request_plan_approval` | Read-only planning with user sign-off |
| **Delegation** | `delegate_to_subagent` | Route tasks to specialist subagents |
| **Other** | `create_checkpoint`, `clarify` | Save progress, ask structured questions |

### Multi-LLM Support

Works with any OpenAI-compatible API. Tested with:

- **Anthropic Claude** (Sonnet, Opus, Haiku) -- with prompt caching
- **OpenAI GPT** (GPT-4o, GPT-4.1, o3)
- **Alibaba Qwen** (Qwen3-Coder, Qwen2.5-Coder)
- **DeepSeek** (DeepSeek-V3, DeepSeek-Coder)
- **Ollama** (any local model)
- Any OpenAI-compatible endpoint (vLLM, LM Studio, LocalAI, llama.cpp)

### Prompt Caching

Automatic prompt caching for Anthropic and compatible providers. The built-in `CacheTracker` reports cache hit rates and effective cost savings (typically 50-80% reduction on long sessions). Cache metrics are logged per session.

### Session Persistence

Every session is saved as append-only JSONL in `.clarity/sessions/`. Resume any previous session with full conversation history, tool call results, and context intact.

### Structured Logging & Observability

All logs go to `.clarity/logs/app.jsonl` as structured JSONL -- no console noise, no TUI interference. Query logs with:

```bash
python -m src.observability.log_query --tail 50
```

Performance metrics and error tracking stored in `.clarity/metrics.db` (SQLite).

## SubAgents

The agent delegates specialized tasks to focused subagents, each with their own system prompt and optional tool restrictions:

| SubAgent | Purpose |
|----------|---------|
| **code-reviewer** | Analyzes code quality, security vulnerabilities, performance issues, and best practices |
| **test-writer** | Creates comprehensive test suites with unit, integration, and edge case coverage |
| **doc-writer** | Writes clear technical documentation for APIs, guides, and architecture |
| **code-writer** | Implements minimum code to satisfy requirements -- focused on writing, not exploration |
| **explore** | Fast read-only codebase explorer for finding code and tracing execution flows |
| **planner** | Produces detailed step-by-step implementation plans without writing code |
| **general-purpose** | Versatile agent with full tool access for multi-step research and implementation |
| **knowledge-builder** | Autonomously explores a codebase and generates structured knowledge base files |

Each subagent can use a different LLM model (configured per-agent in `config.yaml`). Transcripts are saved to `.clarity/sessions/subagents/`.

## Knowledge Base

ClarAIty loads project knowledge automatically from `.clarity/knowledge/`:

```
.clarity/
  knowledge/
    architecture.md      # System design overview
    conventions.md       # Coding standards
    api-patterns.md      # API design patterns
    deployment.md        # Deployment procedures
```

All `.md` files in this directory are loaded into the agent's context at startup. Use the `knowledge-builder` subagent to auto-generate these files from your codebase.

**File-based memory hierarchy** (4 levels, highest to lowest priority):

1. **Enterprise** -- `/etc/clarity/memory.md` (Linux) or `C:/ProgramData/clarity/memory.md` (Windows)
2. **User** -- `~/.clarity/memory.md`
3. **Project** -- `./.clarity/memory.md` (version-controlled, team-shareable)
4. **Imports** -- `@path/to/file.md` syntax for modular includes (circular detection built-in)

## Permission Modes

Three modes control how the agent handles tool approval:

| Mode | Behavior | Toggle |
|------|----------|--------|
| **Normal** (default) | Asks approval for write/edit/run operations | `/mode n` or `Alt+M` |
| **Auto** | Executes all tools without asking | `/mode a` |
| **Plan** | Read-only -- write operations are blocked entirely | `/mode p` |

Switch modes mid-session with `/mode` or `Alt+M` in the TUI.

## MCP Integration

Extend the agent with external services via [Model Context Protocol](https://modelcontextprotocol.io/) servers. MCP tools are discovered dynamically and merged with native tools.

Configure in `.clarity/config.yaml`:

```yaml
mcp_servers:
  - name: jira
    server_url: http://localhost:3000/sse
    tool_prefix: jira_
    connect_timeout: 30
    invoke_timeout: 60
```

Supports both SSE (remote) and stdio (local) transports. Tools are namespaced with configurable prefixes to avoid collisions.

## Configuration

All configuration lives in `.clarity/config.yaml`:

```yaml
logging:
  level: INFO
  handlers:
    jsonl: INFO
  retention:
    jsonl_max_bytes: 52428800

llm:
  backend_type: openai
  base_url: https://api.openai.com/v1
  model: gpt-4o
  context_window: 128000
  temperature: 0.2
  max_tokens: 16384

  # Per-subagent model overrides
  subagents:
    code-reviewer:
      model: claude-sonnet-4-5-20250929
    test-writer:
      model: claude-sonnet-4-5-20250929
```

**Environment variables** override config file values:

| Variable | Purpose |
|----------|---------|
| `LLM_API_KEY` | API key for the LLM provider |
| `LLM_BASE_URL` | API endpoint URL |
| `LLM_MODEL` | Model name |
| `LLM_BACKEND_TYPE` | Backend type (`openai`, `ollama`) |

**Supported backends:** `openai` (default), `ollama`, `vllm`, `localai`, `llamacpp`

## Use Cases

**Feature implementation** -- Ask the agent to add a login page. It reads existing code, plans the approach, writes implementation files, and generates tests using the test-writer subagent.

**Code review** -- Point it at a PR diff or a set of files. The code-reviewer subagent checks for security issues, performance problems, and style violations with a verification-first methodology.

**Codebase exploration** -- Ask "how does authentication work?" The explore subagent traces execution flows across files and reports back with file paths and line numbers.

**Test generation** -- The test-writer subagent analyzes your code, detects the test framework (pytest, jest, vitest, cargo), and generates comprehensive test suites matching existing patterns.

**Documentation** -- The doc-writer subagent generates API docs, architecture guides, or inline documentation based on actual code analysis.

## Installation

### From PyPI

```bash
pip install claraity-code
```

### From Source

```bash
git clone <repo-url>
cd ai-coding-agent
pip install -e ".[dev]"
```

Requires **Python 3.10+**.

### LLM Setup

ClarAIty needs an LLM backend. Choose one:

**Cloud API** (Claude, GPT, etc.):
```bash
export LLM_API_KEY=your-key
export LLM_BASE_URL=https://api.openai.com/v1
export LLM_MODEL=gpt-4o
```

**Local with Ollama:**
```bash
# Install Ollama from https://ollama.ai
ollama pull qwen2.5-coder:7b
export LLM_BACKEND_TYPE=ollama
export LLM_MODEL=qwen2.5-coder:7b
```

## Development

```bash
# Run tests
pytest tests/

# Run a specific test file
pytest tests/tools/test_file_operations.py -v

# Query structured logs
python -m src.observability.log_query --tail 50

# Launch TUI in development
python -m src.cli --tui
```

## License

MIT License. See [LICENSE](LICENSE) for details.
