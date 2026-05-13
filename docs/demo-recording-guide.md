# ClarAIty Demo Recording Guide

Recording guide for creating visual assets (GIFs/videos) for the VS Code Marketplace listing, claraity.dev, and GitHub README.

---

## Tools Needed

- **ScreenToGif** (https://www.screentogif.com/) — free, Windows, frame editor with compression
- **VS Code** with ClarAIty installed
- A sample project (use this repo or a small open-source project)

## Recording Settings

| Setting | Value |
|---------|-------|
| Resolution | 1280x720 (16:9, fits marketplace well) |
| FPS | 10-15 (keeps GIF size manageable) |
| Max duration | 30-45 seconds per GIF |
| Output format | GIF for marketplace/README, MP4 for website |
| Theme | VS Code Dark+ (most recognizable) |
| Font size | 14-16px (readable at embedded sizes) |

## Prep Checklist

- [ ] Close all unrelated VS Code tabs
- [ ] Hide status bar items that show personal info
- [ ] Use a clean workspace name (e.g., "my-project")
- [ ] Set VS Code zoom to 100%
- [ ] Ensure ClarAIty sidebar is visible
- [ ] Pre-load a real project so knowledge DB and sessions exist

---

## GIF 1: Hero Demo — "See Everything the Agent Does" (Primary Asset)

**Purpose:** First thing visitors see. Must answer: "What does this tool actually look like?"
**Duration:** 30-40 seconds
**Where it goes:** Marketplace hero image, claraity.dev above the fold, GitHub README

### Script

1. **Open VS Code** with a real project loaded (this repo works)
2. **Show the ClarAIty sidebar** — conversation is empty
3. **Type prompt:** `Find all TODO comments in the codebase and create a summary`
4. **As the agent runs, the camera captures:**
   - The agent's thinking/response streaming in the chat
   - Tool cards appearing: `grep` searching for TODOs, `read_file` opening files
   - Each tool card shows the tool name, parameters, and result preview
   - The real-time trace showing packets flowing between Agent -> LLM -> Tools
5. **Agent completes** — shows the summary with file locations
6. **Pause 2 seconds** on the final result

### What this demonstrates
- Real-time transparency (tool cards)
- Autonomous multi-step execution
- Useful output from a single prompt

### Tips
- Pick a prompt where the agent uses 3-4 tools visibly
- If the agent is too fast, use a slightly complex prompt
- The trace viewer animation is the money shot — make sure it's visible

---

## GIF 2: Safety & Approval Flow (Trust Asset)

**Purpose:** Shows the agent asks before acting. Key differentiator.
**Duration:** 20-30 seconds
**Where it goes:** Below "Safety and Control" section

### Script

1. **Start with auto-approve OFF** for edits (default)
2. **Type prompt:** `Add error handling to the main entry point`
3. **Agent reads the file** (auto-approved, tool card shows)
4. **Agent proposes an edit** — approval card appears:
   - Shows the tool name (`edit_file`)
   - Shows the file path and proposed changes
   - **[Approve]** and **[Reject]** buttons visible
5. **Click Approve** — the edit applies
6. **VS Code diff editor opens** showing the change with green/red highlighting
7. **CodeLens buttons visible:** Accept | Reject | View Diff

### What this demonstrates
- Agent pauses for destructive operations
- User reviews before anything changes
- Full VS Code diff integration
- One-click undo

---

## GIF 3: Knowledge Graph Visualization (Wow Factor Asset)

**Purpose:** Most visually distinctive feature. Nothing else in the market looks like this.
**Duration:** 20-25 seconds
**Where it goes:** Below "Live Architecture Visualization" section, also good for social media

### Script

1. **Open the Architecture tab** in the ClarAIty sidebar
2. **Show the D3.js graph** — modules as nodes, edges as connections
3. **Hover over a module** — connected edges highlight, tooltip shows details
4. **Click to expand a module** — components appear inside
5. **Click a component** — detail drawer opens showing:
   - Description
   - Risk level
   - File paths
   - Incoming/outgoing dependencies
6. **Click "Discuss with AI"** — switches to chat with the component context pre-loaded

### What this demonstrates
- Interactive architecture exploration
- Autonomous codebase understanding
- Seamless transition from visualization to AI conversation

---

## GIF 4: BYO Model + Subagents (Flexibility Asset)

**Purpose:** Shows model independence and specialization. Appeals to power users.
**Duration:** 20-25 seconds
**Where it goes:** Below "Any LLM" and "Custom Subagents" sections

### Script

1. **Open Settings** (gear icon)
2. **Show the LLM configuration** — multiple providers visible
3. **Show model dropdown** — auto-fetched model list from the provider
4. **Switch to Subagents tab** — list of built-in subagents visible
5. **Click a subagent** (e.g., code-reviewer) — shows system prompt, tool restrictions, model override
6. **Back to chat, type:** `/code-review src/core/agent.py`
7. **Show the skill activating** and the code-reviewer subagent launching

### What this demonstrates
- Provider flexibility (not locked into one vendor)
- Specialized agents for specific tasks
- Slash commands for quick access

---

## GIF 5: Turn Undo & Context Control (Safety Net Asset)

**Purpose:** Shows users they're never stuck. Agent mistakes are reversible.
**Duration:** 15-20 seconds
**Where it goes:** Below "Safety and Control" section or as a secondary trust asset

### Script

1. **Show a conversation** with 3-4 turns already completed
2. **Agent made a change in the last turn** (file was edited)
3. **Click the undo/delete button** on the last turn
4. **Turn collapses** — shows "[Turn deleted]" placeholder
5. **File reverts** to its previous state
6. **Click restore** — turn reappears, file change re-applies

### What this demonstrates
- Non-destructive editing
- Full reversibility
- User remains in control

---

## GIF 6: .claraityignore Safety (Enterprise Trust Asset)

**Purpose:** Shows file-level protection. Critical for enterprise adoption.
**Duration:** 15-20 seconds
**Where it goes:** Safety section or enterprise-focused content

### Script

1. **Show `.claraityignore` file** in the editor with entries:
   ```
   .env
   secrets/
   *.key
   ```
2. **Type prompt:** `Read the contents of .env`
3. **Agent attempts to read** — tool card shows "Access denied: file is blocked by user policy"
4. **Type prompt:** `Search for API keys in the project`
5. **Agent searches** — results automatically exclude `.env` and `secrets/` files

### What this demonstrates
- Fine-grained file protection
- Blocks ALL access paths (read, search, shell commands)
- Familiar gitignore syntax

---

## GIF 7: Prompt Enrichment (Smart Input Asset)

**Purpose:** Shows the "prompt engineering as a service" feature. Unique to ClarAIty.
**Duration:** 20-25 seconds
**Where it goes:** Below prompt enrichment section, great for social media

### Script

1. **Enable enrichment** — click the sparkle icon in the input box (it highlights)
2. **Type a vague prompt:** `fix the auth thing`
3. **Enrichment runs** — streaming text appears showing the rewrite
4. **Side-by-side preview appears:**
   - Original: "fix the auth thing"
   - Enriched: "Fix the authentication error in src/auth.py where the login() function fails when passwords contain special characters. Add input sanitization and update the corresponding test."
5. **User edits the enriched prompt** slightly (optional — shows it's editable)
6. **Click Send** — enriched prompt goes to the agent

### What this demonstrates
- Vague input becomes precise instructions
- User stays in control (can edit before sending)
- Configurable (sparkle toggle, custom model/prompt)

---

## Asset Placement Map

| Asset | Marketplace README | claraity.dev | GitHub | Social |
|-------|-------------------|--------------|--------|--------|
| GIF 1 (Hero) | Hero image | Above fold | Top of README | Launch post |
| GIF 2 (Safety) | Safety section | Features | Safety section | Trust post |
| GIF 3 (Knowledge) | Knowledge section | Features | Knowledge section | Wow post |
| GIF 4 (BYO Model) | LLM section | How it works | - | Flexibility post |
| GIF 5 (Undo) | Safety section | - | - | - |
| GIF 6 (Ignore) | Safety section | Enterprise | - | Enterprise post |
| GIF 7 (Enrichment) | LLM section | Features | - | Smart input post |

## Priority Order

Record them in this order (highest impact first):
1. **GIF 1** — blocks everything else (hero image needed for README rewrite)
2. **GIF 3** — most visually distinctive, great for social shares
3. **GIF 2** — trust builder, needed for enterprise positioning
4. GIF 4-6 — nice-to-have, create after launch

## Post-Processing Tips

- **ScreenToGif editor:** Remove dead frames (waiting, typing slowly)
- **Add a 2-second hold** on the final frame so viewers can absorb the result
- **Target file size:** Under 5MB per GIF for marketplace (they compress poorly)
- **For MP4 (website):** Same recordings but export as MP4 — 10x smaller, autoplay with loop
- **Add captions/annotations** in ScreenToGif if the action isn't self-explanatory
