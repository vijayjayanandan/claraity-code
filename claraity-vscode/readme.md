# ClarAIty — AI Coding Agent That Brings Visual Clarity to Your Codebase and Every AI Interaction

ClarAIty is an AI coding agent that doesn't just write code — it **understands your codebase**, shows you exactly what it's doing, and puts you in control of every decision. Powered by **any LLM you choose**.

---

## Codebase Intelligence

ClarAIty autonomously scans your codebase and builds a **queryable knowledge database** — modules, components, dependencies, architectural decisions, and invariants. No manual documentation required.

- **Autonomous scanning** — the Knowledge Builder subagent explores your project and maps its architecture
- **Queryable knowledge** — ask about modules, trace dependencies, assess impact of changes
- **Drift detection** — detects when files change and scopes incremental updates
- **Git-trackable** — knowledge exports to JSONL, so your architecture documentation lives alongside your code and evolves with it

## Live Architecture Visualization

See your codebase as an **interactive D3.js dependency graph** — right inside VS Code.

- **Progressive disclosure** — collapsed modules at L1, expand to see components at L2, full detail at L3
- **Edge interaction** — hover to reveal dependencies, click to lock, color-coded by relationship type
- **Detail drawer** — descriptions, risk levels, file paths, incoming/outgoing relationships
- **Discuss with AI** — click any node and ask the agent about it with full architectural context injected automatically
- **Review workflow** — approve or reject scanned knowledge with comments

## AI Interaction Tracing

Watch the agent think in real time. The **Trace Viewer** animates every step of the agent's pipeline so you always know what's happening and why.

- **7-node pipeline diagram** — User, Agent, LLM, Tools, Tool Gating, Store, Context Builder
- **Animated execution flow** — packets travel between nodes as the agent processes your request
- **Context assembly breakdown** — see exactly what context (system prompt, knowledge DB, memory, conversation history) is sent to the LLM
- **Tool gating visualization** — watch the 4-layer safety pipeline evaluate each tool call
- **Subagent tracing** — seamless scene swap when work is delegated to a subagent
- **Expandable detail** — click any step to inspect the full content, thinking, and tool parameters

## Any LLM, Your Choice

Use OpenAI, Anthropic Claude, Ollama (local), DeepSeek, Kimi, or **any OpenAI-compatible API**. Switch models mid-session without restarting.

- **Per-subagent model overrides** — use a fast model for exploration, a powerful model for code review
- **Auto-fetched model lists** — models are fetched from your provider automatically
- **Hot-swap configuration** — change settings without restarting the agent

## Custom Subagents

Create purpose-built agents tailored to your workflow, or fork and customize the built-ins.

- **Built-in specialists** — code-reviewer, test-writer, doc-writer, explore, planner, knowledge-builder, and more
- **Create your own** — define a name, system prompt, and tool restrictions
- **Fork built-ins** — clone any built-in subagent and customize it for your needs
- **Per-agent tool access** — restrict which tools each subagent can use
- **Model overrides** — assign different LLM models to different subagents from the Settings panel

## Persistent Task Tracking

A built-in task management system inspired by the **Beads** methodology — tracks work across sessions and exports alongside your code.

- **Status workflow** — Ready, In Progress, Blocked, Deferred, Pinned, Closed
- **Hierarchical tasks** — epics with nested subtasks and progress tracking
- **Priority levels** — P0-P3 with visual indicators and filtering
- **Rich metadata** — descriptions, acceptance criteria, blockers, due dates, tags, external references
- **Two views** — Queue view (action-oriented) and Epics view (progress-oriented)
- **Git-trackable** — exports to JSONL so task state is versioned with your code

## Safety and Control

ClarAIty's multi-layered safety system ensures the agent asks before acting.

- **4-layer tool gating** — repeat detection, plan mode, director workflow, and approval
- **`.claraityignore`** — protect sensitive files with gitignore-style patterns; blocked files cannot be read, written, or passed to commands
- **Auto-approve categories** — toggle approval for reads, edits, commands, browser, knowledge updates, and subagent delegation independently
- **Iteration limits** — configurable cap on agent iterations per turn
- **Diff approval** — review every proposed change in VS Code's diff editor before accepting
- **Turn-level undo** — revert all changes from any agent turn with one click

## Persistent Memory

Every conversation is saved and resumable. The agent maintains context intelligently across turns.

- **Session persistence** — conversations saved to JSONL, browse and resume any time
- **Working memory** — the agent tracks what it's learned within a session
- **Intelligent compaction** — old messages are compacted when approaching context limits
- **Multi-level context** — system prompt, project instructions, knowledge DB, memory files, and conversation history assembled each turn

## 30+ Built-in Tools

Parallel execution, intelligent error recovery, and configurable timeouts.

| Category | Tools |
|----------|-------|
| **File Operations** | read, write, edit, append, list directory |
| **Search** | grep (regex), glob (patterns), web search, web fetch |
| **Code Intelligence** | file outlines, symbol context via LSP |
| **Execution** | shell commands, background tasks |
| **Knowledge** | scan, query, update architecture DB |
| **Tasks** | create, update, list Beads tasks |
| **Planning** | plan mode, checkpoints, clarify questions |
| **Delegation** | delegate to any subagent |

## MCP Integration

Extend the agent with **Model Context Protocol** servers — connect to databases, APIs, and external tools.

- **Marketplace** — browse and install MCP servers from the registry and npm
- **Per-tool toggles** — enable or disable individual tools from each server
- **Project or global** — install servers at project level or system-wide
- **Auto-reconnect** — servers reconnect automatically on startup

## Deep VS Code Integration

Not just a chat window — ClarAIty integrates deeply into the editor.

- **CodeLens** — inline Accept / Reject / View Diff buttons on modified files
- **File decorations** — "AI" badges on files the agent modified
- **Diff editor** — full VS Code diff view for proposed changes
- **Context menu** — right-click selected code to explain, fix, refactor, or send to chat
- **@file mentions** — type `@` in the chat input to reference files by name
- **Image support** — paste or drag images into chat for visual context
- **Terminal echo** — agent commands displayed in a dedicated terminal
- **Cost tracking** — token usage and estimated cost per response

## Getting Started

### 1. Install

Install ClarAIty from the VS Code Marketplace. The extension bundles a self-contained agent binary — **no Python installation required**.

### 2. Configure Your LLM

Click the gear icon in the sidebar to open Settings. Enter your API base URL, API key, and select a model. Supports OpenAI, Anthropic, Ollama, Azure OpenAI, Groq, Together.ai, DeepSeek, Kimi, and any OpenAI-compatible endpoint.

### 3. Start Chatting

Type a message in the chat input. The agent will analyze your workspace, read relevant files, and respond with context-aware assistance.

**Try these first messages:**
- "Explain the architecture of this project"
- "Find and fix bugs in src/auth.ts"
- "Write unit tests for the User model"
- "Scan this codebase and build the knowledge database"

### 4. Review and Approve

When the agent proposes file changes, you'll see a diff preview. Click **Accept** to apply or **Reject** to decline. Use the auto-approve toggle for trusted operations like file reads and searches.

## Keyboard Shortcuts

| Action | Windows/Linux | Mac |
|--------|---------------|-----|
| New Chat | `Ctrl+Shift+L` | `Cmd+Shift+L` |
| Interrupt Agent | `Ctrl+Shift+.` | `Cmd+Shift+.` |
| Session History | `Ctrl+Shift+;` | `Cmd+Shift+;` |
| Add Selection to Chat | `Ctrl+'` | `Cmd+'` |
| New Line in Message | `Shift+Enter` | `Shift+Enter` |
