# ClarAIty Launch Posts

---

## Show HN Post

### Title (under 80 chars)
**Show HN: ClarAIty -- AI coding agent that shows every tool call in real time**

### Body

I built ClarAIty because I was tired of AI coding agents being black boxes. You paste your prompt, wait, and hope it didn't break anything. There's no way to see what it's reading, what context it's using, or why it made a decision.

ClarAIty is a VS Code extension with full transparency. Every file read, every search, every command shows up as a live trace with an animated pipeline diagram. The agent pauses for approval before destructive operations, and you can undo any turn with one click.

Key features:

- **Real-time trace viewer** -- 7-node animated pipeline showing exactly what the agent is doing
- **8-layer safety system** -- hard-blocked dangerous commands, approval workflow for edits, .claraityignore for sensitive files, workspace boundary enforcement
- **Codebase knowledge graph** -- autonomous scanning builds a queryable DB of modules, components, and dependencies with D3.js visualization
- **Any OpenAI-compatible endpoint** -- OpenAI, Anthropic, Ollama (local), DeepSeek, OpenRouter, and more. Assign different models to different subagents from the same provider
- **Custom subagents and skills** -- 8 built-in specialists (code reviewer, test writer, planner, etc.) plus create-your-own via markdown
- **Git-trackable config** -- memories, skills, knowledge, and tasks stored in .claraity/ and travel with the repo

The agent is bundled as a binary with the extension -- no Python install required.

Free, open source, MIT license.

Website: https://claraity.dev
VS Code Marketplace: [link]
GitHub: [link]

Happy to answer questions about the architecture. The agent itself was built with ClarAIty, so the knowledge DB and session history for the entire development process are in the repo.

---

## Product Hunt

### Tagline (60 chars max)
AI coding agent that shows its work -- every tool call, live

### Description (260 chars max)
ClarAIty brings full transparency to AI coding. Watch every file read, search, and edit in real time. 8-layer safety system. Works with any LLM. Codebase knowledge graph. Custom subagents. Git-trackable config. Free VS Code extension.

### Maker Comment

I started building ClarAIty after watching AI coding agents silently break production code one too many times. The problem isn't that AI writes bad code -- it's that you can't see what it's doing until it's too late.

ClarAIty's trace viewer shows every step of the agent's pipeline in real time. The safety system has 8 layers including hard-blocked dangerous commands and .claraityignore for sensitive files. The codebase knowledge graph means the agent actually understands your architecture, not just the file you're editing.

Three things I'm most proud of:

1. The D3.js architecture visualization -- click a node in the graph and ask the AI about it with full context injected

2. Git-trackable everything -- clone the repo, and the new developer's agent already knows the codebase, the decisions, and the task backlog

3. The subagent system -- create specialized agents (markdown file + YAML) with their own models, tools, and system prompts

Works with any OpenAI-compatible LLM. Free and open source.

---

## Twitter/X Thread

### Tweet 1 (hook)
AI coding agents are black boxes.

You paste a prompt and hope for the best.

I built @ClarAItyDev to fix this. It's an AI coding agent that shows you everything -- every file read, every search, every edit, in real time.

Free VS Code extension. Works with any OpenAI-compatible endpoint. [link]

### Tweet 2 (trace viewer)
The Trace Viewer is the core.

A 7-node animated pipeline diagram shows the agent's thinking live:
- What context it assembled
- What tools it's calling
- How the safety system evaluated each call
- When it delegates to a subagent

You never wonder "what is it doing?"

[GIF 1]

### Tweet 3 (safety)
Safety isn't just "click approve."

ClarAIty has 8 layers:
- Hard-blocked: reverse shells, disk wipes, data exfil
- .claraityignore: gitignore-style file protection
- Workspace boundaries: files outside project need approval
- Turn-level undo: revert any agent action

[GIF 2]

### Tweet 4 (knowledge)
Most AI agents understand the file you're editing.

ClarAIty understands your entire codebase.

It autonomously scans and builds a knowledge graph -- modules, components, dependencies, invariants. Queryable. Visualizable. Git-tracked.

"What breaks if I change this?" -> instant answer.

[GIF 3]

### Tweet 5 (flexibility)
Not locked into one LLM.

Works with any OpenAI-compatible endpoint: OpenAI, Anthropic, Ollama (local), DeepSeek, OpenRouter, and more.

If your provider serves multiple models, assign different ones to different subagents. Switch mid-session.

Your API key, your data.

### Tweet 6 (CTA)
ClarAIty is free and open source (MIT).

- Install: [VS Code Marketplace link]
- Source: [GitHub link]
- Site: https://claraity.dev

It was built with itself -- the knowledge DB and full session history of development are in the repo.

Star on GitHub if you think AI should show its work.

---

## Reddit Posts

### r/vscode
**Title:** I built a VS Code extension that traces every AI agent action in real time

**Body:** [Shorter version of HN post, focus on VS Code integration features -- CodeLens, diff editor, file decorations, context menu, keyboard shortcuts]

### r/LocalLLaMA
**Title:** ClarAIty: AI coding agent that works with Ollama and any OpenAI-compatible endpoint

**Body:** [Focus on endpoint flexibility, no data sent to third parties, per-subagent model selection from same provider, self-contained binary]

### r/programming
**Title:** Why I built an "observable" AI coding agent

**Body:** [Focus on the philosophy -- observability for AI should be as natural as observability for production systems]

---

## Launch Timing Checklist

- [ ] GIF 1 (Hero) recorded and embedded in README + website
- [ ] GIF 3 (Knowledge graph) recorded for social posts
- [ ] At least 5 marketplace reviews seeded
- [ ] GitHub README updated with GIFs
- [ ] claraity.dev updated with GIFs + revised copy
- [ ] Twitter/X account created (@ClarAItyDev or similar)
- [ ] Post HN on Tuesday-Thursday, 8-10am ET (peak traffic)
- [ ] Product Hunt scheduled for same week (different day)
- [ ] Reddit posts staggered across 2-3 days after HN
