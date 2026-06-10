---
name: Educational Presentation State
description: Tracking the progress and prompt generation rules for the Telus Health 14-chapter agent demo
type: project
---

# Educational Presentation: From Chat Completion to AI Agent

We are generating a series of 14 prompts to be used in a live demo at Telus Health. The demo builds a "Benefits Navigator Agent" from scratch, layer by layer, to teach AI agent architecture.

## Current Status
- **Completed**: Prompts for Chapters 1-10 are finalized and saved in `docs/educational-readme/presentation/prompts/v2/`.
- **Chapters 11-14**: Slides-only (Knowledge Graph, Task Tracking, Subagents, Big Picture) — no demo prompts needed (too ClarAIty-specific).
- **Glossary**: All 10 demo prompts wired into `glossary.js`. Syntax bug (stray `};` at line 584) fixed.
- **Slides**: `[[Demo Prompt: Chapter X]]` references added to key-insight slides for all 10 chapters.

## Prompt Generation Rules
When generating future prompts, strictly follow these rules:
1. **No Context Boilerplate**: Do NOT include the beginner context boilerplate at the top. Chapter 1 injected this into the demo agent's memory, so subsequent prompts just start with "This is Chapter X..."
2. **Autonomous Task Planning**: Do not spoon-feed subtasks. Instead: "Please follow the rules in your memory to plan and track the subtasks in the task tracker, then build the following:"
3. **The Story**: Always include a `WHAT CHANGED (The Story)` section with a specific analogy.
4. **Naming**: The entry point is `main.py`. The orchestration loop lives in `core/agent.py`.

## Chapter Ordering (final)
1. Brain: Chat Completion
2. Briefing: Context Manager + LLM Abstraction
3. Hands: Tool Calling
4. Guard: Tool Gating
5. Notebook: Session Persistence
6. Conductor: Agent Loop
7. Voice: Streaming UX
8. Safety Net: Error Recovery
9. Summarizer: Context Compaction
10. Connector: MCP
11-14: Slides-only (Wiki, Planner, Team Lead, Big Picture)