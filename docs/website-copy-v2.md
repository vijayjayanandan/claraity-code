# claraity.dev — Revised Website Copy

## Above the Fold

### Headline (Option A — Problem-first)
**AI coding agents are black boxes. This one isn't.**

### Headline (Option B — Benefit-first)
**The AI coding agent that shows its work**

### Headline (Option C — Category-defining)
**Observable AI for software development**

### Subheadline (pairs with any headline)
ClarAIty traces every tool call, every file read, every decision — in real time. Review diffs before they apply. Undo any turn. Use any LLM. Your code, your rules.

### Primary CTA
**Install for VS Code — Free** (marketplace link)

### Secondary CTA
**Watch the 60s demo** (scrolls to embedded video/GIF or plays modal)

### Tertiary CTA
**Star on GitHub** (builds social proof)

---

## Social Proof Bar (below hero, above features)

> "Used by developers at TELUS" (if approved)

Or, before you have testimonials:

**Open source | MIT License | Works with any OpenAI-compatible API**

---

## Feature Sections (restructured for hierarchy)

### Section 1: "See everything the agent does"
*Lead feature — this is the differentiator*

Every file read, every grep, every command — displayed as a live trace with animated execution flow. No hidden operations. No surprises.

- 7-node pipeline diagram: User -> Agent -> LLM -> Tools -> Gating -> Store -> Context
- Click any step to inspect full content and parameters
- Subagent delegation traced seamlessly

**[GIF 1 — Hero demo embedded here]**

---

### Section 2: "The agent asks before it acts"
*Trust feature — answers "is it safe?"*

An 8-layer safety system protects your code by default. Hard-blocked commands (disk destruction, reverse shells) can never execute. Everything else requires your approval.

- .claraityignore — protect sensitive files with gitignore patterns
- Diff review — every edit shown in VS Code's diff editor
- Turn-level undo — revert any agent action with one click
- Workspace boundary enforcement — files outside your project need explicit approval

**[GIF 2 — Approval flow embedded here]**

---

### Section 3: "It understands your codebase"
*Depth feature — answers "what makes this different from ChatGPT?"*

ClarAIty scans your project and builds a knowledge graph — modules, components, dependencies, architectural decisions. Query it. Visualize it. Track its evolution in git.

- Interactive D3.js architecture graph inside VS Code
- Impact analysis: "what breaks if I change this?"
- Git-trackable JSONL exports — architecture docs evolve with your code
- Clone the repo and the new developer's agent already knows the codebase

**[GIF 3 — Knowledge graph embedded here]**

---

### Section 4: "Use any LLM"
*Flexibility feature — answers "am I locked in?"*

OpenAI, Claude, Ollama (local), DeepSeek, Kimi, Azure, Groq, Together.ai, or any OpenAI-compatible endpoint. Switch models mid-session. Assign different models to different subagents.

Your API key, your data. Nothing routes through our servers.

---

### Section 5: "Extend it your way"
*Power-user feature — answers "can it fit my workflow?"*

- **8 built-in subagents** — code reviewer, test writer, doc writer, explorer, planner, and more
- **Custom skills** — drop a markdown file, get a slash command
- **MCP integration** — connect to databases, APIs, and external tools
- **Git-trackable config** — memories, skills, subagents, and knowledge travel with your repo

---

## "How it works" Section (simplified)

### Step 1: Install
One click from the VS Code Marketplace. No Python required — the agent binary is bundled.

### Step 2: Add your API key
Any LLM provider. Stored securely in VS Code settings.

### Step 3: Ask it anything
"Explain this codebase." "Find and fix the auth bug." "Write tests for the User model."

### Step 4: Stay in control
Review diffs. Approve or reject. Undo any turn. Auto-approve what you trust.

---

## Bottom CTA (above footer)

### Heading
**Start building with clarity**

### Body
Free and open source. Install in 30 seconds. Works with any LLM.

### Buttons
- **Install for VS Code** (primary)
- **View source on GitHub** (secondary)
- **Join the community** (Discord/Discussions link — add when ready)

---

## SEO / Meta Tags

```html
<title>ClarAIty — AI Coding Agent with Full Transparency | VS Code Extension</title>
<meta name="description" content="AI coding agent that shows every tool call, every decision, in real time. 8-layer safety system. Works with any LLM. Free and open source VS Code extension.">
<meta name="keywords" content="AI coding agent, VS Code extension, code assistant, transparent AI, LLM coding, Copilot alternative, AI code review, codebase intelligence">
```

---

## Positioning Comparison (for reference, not published)

| Dimension | Copilot | Cursor | Cline / Roo | ClarAIty |
|-----------|---------|--------|-------------|----------|
| Transparency | Low | Medium | Medium | **Full trace** |
| Safety layers | Basic | Basic | Approval-only | **8-layer pipeline** |
| Model lock-in | GitHub/OpenAI | Anthropic/OpenAI | Any | **Any endpoint — per-subagent model selection** |
| Codebase understanding | Repo-level | File-level | File-level | **Knowledge graph** |
| Prompt assistance | None | None | None | **Prompt enrichment with configurable model** |
| Customization | None | Cursor rules | MCP | **Subagents + Skills + MCP** |
| Git-trackable config | No | .cursorrules | No | **Full (.claraity/)** |
| Self-hostable | No | No | Yes | **Yes** |
| Price | $10-39/mo | $20/mo | Free | **Free** |
