# ClarAIty — The AI Coding Agent You Can Actually Trust

<!-- GIF 1: Hero demo showing agent working with trace viewer visible -->
<!-- ![ClarAIty in action](images/hero-demo.gif) -->

AI coding agents are powerful — but they're black boxes. You hit Enter and hope for the best.

**ClarAIty shows you everything.** Every file it reads, every command it runs, every decision it makes — displayed in real time. And it **asks before it acts**.

Powered by **any LLM you choose**. No vendor lock-in.

[![Install for VS Code](https://img.shields.io/badge/Install-VS%20Code%20Marketplace-blue)](https://marketplace.visualstudio.com/items?itemName=claraity.claraity-code)
[![GitHub](https://img.shields.io/github/stars/vjgpt/claraity-code?style=social)](https://github.com/vjgpt/claraity-code)

---

## Why ClarAIty?

| Other AI Agents | ClarAIty |
|---|---|
| You see the final result | You see **every step** — reads, searches, edits, commands |
| Changes happen silently | **Approval workflow** — review diffs before they apply |
| Locked to one model | **Any OpenAI-compatible endpoint** — assign different models to different subagents |
| Agent forgets between sessions | **Persistent knowledge DB** — scans your codebase, remembers across sessions |
| Configuration in code | **Git-trackable project config** — memories, skills, knowledge travel with the repo |
| You write the prompt | **Prompt enrichment** — rewrites vague prompts into precise instructions before sending |

---

## Real-Time Tool Tracing

<!-- GIF 2: Trace viewer animation -->
<!-- ![Trace Viewer](images/trace-demo.gif) -->

Watch the agent think. The **Trace Viewer** animates every step of the pipeline so you always know what's happening and why.

- **7-node pipeline diagram** — User, Agent, LLM, Tools, Tool Gating, Store, Context Builder
- **Animated execution flow** — packets travel between nodes as the agent works
- **Context assembly breakdown** — see exactly what's sent to the LLM (system prompt, knowledge, memory, history)
- **Tool gating visualization** — watch the safety pipeline evaluate each tool call
- **Subagent tracing** — seamless scene swap when work is delegated

---

## Multi-Layer Safety System

<!-- GIF 3: Approval flow demo -->
<!-- ![Safety & Approval](images/safety-demo.gif) -->

ClarAIty doesn't just ask "are you sure?" — it has an **8-layer safety pipeline** that protects you by default.

### What's Protected

| Layer | What It Does |
|-------|-------------|
| **Repeat detection** | Blocks identical failed tool calls |
| **Plan mode** | Read-only mode — blocks all writes |
| **Command hard-block** | Permanently blocks disk destruction, reverse shells, data exfiltration, encoded payloads |
| **Command approval** | Requires confirmation for recursive delete, credential access, permission changes |
| **Workspace boundary** | Requires approval for files outside your project — even if reads are auto-approved |
| **`.claraityignore`** | Gitignore-style policy file — blocked files can't be read, written, searched, or passed to commands |
| **Category auto-approve** | Toggle approval per category: reads, edits, commands, browser, knowledge, subagents |
| **Diff review** | Every proposed change shown in VS Code's diff editor — Accept or Reject per file |

### `.claraityignore` — File-Level Protection

```gitignore
# Protect secrets
.env
credentials/
*.key
*.pem

# Protect sensitive data
customer-data/
!customer-data/schema.sql
```

Blocked files are invisible to the agent. It can't read them, search for them, or reference them in shell commands. Patterns reload live — no restart needed.

### Turn-Level Undo

Made a mistake? Click undo on any turn. All file changes from that turn revert instantly. Click restore to bring them back. Non-destructive and reversible.

---

## Codebase Intelligence

<!-- GIF 4: Knowledge graph demo -->
<!-- ![Knowledge Graph](images/knowledge-demo.gif) -->

ClarAIty autonomously scans your project and builds a **queryable knowledge database** — no manual documentation required.

- **Autonomous scanning** — the Knowledge Builder subagent maps modules, components, dependencies, and invariants
- **Impact analysis** — "what breaks if I change this?" with blast radius visualization
- **Drift detection** — detects file changes and scopes incremental updates
- **Full-text search** — FTS5-powered search across all codebase entities
- **Git-trackable** — exports to JSONL, so architecture docs evolve with your code

### Live Architecture Visualization

See your codebase as an **interactive D3.js dependency graph** — right inside VS Code.

- Collapsed modules at L1, expand to components at L2, full detail at L3
- Hover to reveal dependencies, click to lock, color-coded by relationship type
- Click any node and ask the agent about it — architectural context injected automatically

---

## Any LLM, Your Choice

Connect to OpenAI, Anthropic Claude, Ollama (local), DeepSeek, Kimi, Azure OpenAI, Groq, Together.ai, OpenRouter, or **any OpenAI-compatible endpoint**. If your provider serves multiple models, assign different ones to different subagents.

- **Switch mid-session** — change models without restarting
- **Per-subagent model selection** — powerful model for code review, fast model for exploration (same endpoint)
- **Auto-fetched model lists** — models discovered from your provider automatically
- **Your API key, your data** — nothing routes through our servers

### Prompt Enrichment

ClarAIty can rewrite your prompts before they reach the agent. Vague requests become precise instructions.

- **Side-by-side preview** — see original and enriched prompt, edit before sending
- **Context-aware** — uses recent conversation history to resolve ambiguous references
- **Configurable model** — use a fast/cheap model for enrichment, powerful model for the agent
- **Custom enrichment prompt** — change how rewriting works via Settings
- **One-click toggle** — sparkle icon to enable/disable per message

---

## Custom Subagents

Create purpose-built AI agents tailored to your workflow.

**8 built-in specialists:**

| Subagent | Purpose |
|----------|---------|
| **code-reviewer** | Security, performance, correctness analysis |
| **test-writer** | Unit tests, integration tests, edge cases |
| **doc-writer** | Technical documentation |
| **code-writer** | Minimum code to satisfy requirements |
| **explore** | Fast read-only codebase exploration |
| **planner** | Step-by-step implementation plans |
| **general-purpose** | Multi-step research and implementation |
| **knowledge-builder** | Autonomous codebase scanning |

**Fully customizable:**
- Create your own with a markdown file + YAML frontmatter
- Fork any built-in and modify it
- Restrict tool access per subagent
- Assign different LLM models to different subagents
- Run up to 4 subagents in parallel

---

## Skills — Reusable Workflows

Skills are procedural instructions that guide the agent for specific tasks. Activate with slash commands.

**Built-in skills:**

| Skill | Command | What It Does |
|-------|---------|-------------|
| Code Review | `/code-review` | Structured review: correctness, security, performance |
| Test-Driven Bugfix | `/test-driven-bugfix` | Write failing test first, then fix the bug |
| Safe Refactor | `/safe-refactor` | Refactor with test verification at each step |
| Pre-Commit Review | `/pre-commit-review` | Review staged changes before committing |
| Release | `/release` | Release management workflow |
| Build | `/build` | Build and packaging workflow |

**Create your own:** Drop a markdown file in `.claraity/skills/` — it becomes a slash command automatically. Supports shell preprocessing, argument substitution, and helper scripts.

---

## Persistent Task Tracking

A built-in task management system inspired by the **Beads** methodology.

- **Status workflow** — Ready, In Progress, Blocked, Deferred, Pinned, Closed
- **Dependency graph** — tasks block each other automatically; ready queue shows only unblocked work
- **Hierarchical tasks** — epics with nested subtasks and progress tracking
- **Atomic claiming** — prevents double-work across sessions
- **Full audit trail** — every status change logged with timestamp
- **Git-trackable** — exports to JSONL alongside your code

---

## Persistent Memory

Conversations are saved and resumable. Context is managed intelligently.

- **Session persistence** — full conversations saved to JSONL, browse and resume any time
- **Project memories** — markdown files in `.claraity/memory/` with YAML frontmatter, git-tracked
- **Intelligent compaction** — when approaching context limits, priorities: user messages > code > errors > decisions
- **Multi-level context assembly** — system prompt + knowledge DB + memories + conversation history, built fresh each turn

### Git-Trackable Everything

ClarAIty stores its knowledge **alongside your code** in `.claraity/`:

```
.claraity/
  memory/          # Project memories (git-tracked)
  skills/          # Custom skills (git-tracked)
  agents/          # Custom subagents (git-tracked)
  plans/           # Implementation plans (git-tracked)
  claraity_knowledge.jsonl  # Codebase knowledge (git-tracked)
  claraity_beads.jsonl      # Task records (git-tracked)
```

Clone the repo, and the new developer's agent already knows the architecture, the decisions, the task backlog, and the team's workflows. No onboarding document needed.

---

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

---

## MCP Integration

Extend the agent with **Model Context Protocol** servers — connect to databases, APIs, and external tools.

- Browse and install from the MCP registry and npm
- Per-tool toggles — enable or disable individual tools from each server
- Project or global scope
- Auto-reconnect on startup

---

## Deep VS Code Integration

Not just a chat window — ClarAIty integrates into the editor.

- **CodeLens** — inline Accept / Reject / View Diff on modified files
- **File decorations** — "AI" badges on files the agent modified
- **Diff editor** — full VS Code diff view for proposed changes
- **Context menu** — right-click code to explain, fix, refactor, or send to chat
- **@file mentions** — type `@` to reference files by name
- **Image support** — paste or drag images into chat
- **Terminal echo** — agent commands in a dedicated terminal
- **Cost tracking** — token usage and estimated cost per response

---

## Getting Started

### 1. Install

Install ClarAIty from the VS Code Marketplace. The extension bundles a self-contained agent binary — **no Python installation required**.

### 2. Configure Your LLM

Click the gear icon in the sidebar. Enter your API base URL, API key, and select a model.

### 3. Start Chatting

Type a message. The agent analyzes your workspace, reads relevant files, and responds with context-aware assistance.

**Try these first:**
- `Explain the architecture of this project`
- `Find and fix bugs in src/auth.ts`
- `Write unit tests for the User model`
- `Scan this codebase and build the knowledge database`

### 4. Review and Approve

The agent proposes changes as diffs. Click **Accept** to apply or **Reject** to decline. Toggle auto-approve for trusted operations.

---

## Keyboard Shortcuts

| Action | Windows/Linux | Mac |
|--------|---------------|-----|
| New Chat | `Ctrl+Shift+L` | `Cmd+Shift+L` |
| Interrupt Agent | `Ctrl+Shift+.` | `Cmd+Shift+.` |
| Session History | `Ctrl+Shift+;` | `Cmd+Shift+;` |
| Add Selection to Chat | `Ctrl+'` | `Cmd+'` |
| New Line in Message | `Shift+Enter` | `Shift+Enter` |

---

## Links

- [Website](https://claraity.dev)
- [GitHub](https://github.com/vjgpt/claraity-code)
- [Report Issues](https://github.com/vjgpt/claraity-code/issues)

**MIT License** | Built by [claraity](https://claraity.dev)
