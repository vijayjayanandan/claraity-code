# Video 1: The Big Picture
## "Follow a Message Through the Entire ClarAIty Agent"

**Duration:** 8-10 minutes
**Goal:** Give the viewer a complete mental map of how the agent works, end to end. After this video, they should be able to point to any part of the system and say "I know what that does and how it connects to the rest."

---

## COLD OPEN (0:00 - 0:30)

> **[SCREEN: The TUI running. User types "fix the null check bug in auth.py" and presses Enter. The agent streams a response, reads a file, edits it, runs tests. Response completes.]**

**NARRATION:**

"What you just saw took about 15 seconds. But behind the scenes, your message traveled through 6 layers of code, triggered an async generator, made multiple round-trip calls to an LLM, passed through a 4-gate security system, executed tools in a sandboxed environment, and streamed results back through two parallel paths - one for your screen, one for persistence.

Let's trace that entire journey, step by step."

> **[SCREEN: Fade to the architecture diagram from agent-lifecycle.md]**

---

## ACT 1: STARTUP - "Building the Factory Before the First Order" (0:30 - 2:30)

> **[SCREEN: Terminal showing `python -m src.cli`]**

**NARRATION:**

"Before a single message can be processed, the agent has to build itself. Think of it like a factory. Before the first customer order arrives, you need the assembly line set up, the tools laid out, the quality inspectors in position, and the shipping department ready.

Let's watch that factory come online."

### Scene 1.1: Module-Level Setup (0:30 - 1:00)

> **[SCREEN: `cli.py` lines 9-34, highlighting each line as it's narrated]**

"The moment Python loads `cli.py`, before any function even runs, four things happen at the module level:

First, on Windows, we clean up the `TERM` environment variable. This prevents a terminal library called prompt_toolkit from thinking it's running on Linux.

Second, we set Windows' async I/O policy. Python's default event loop on Windows can't handle some operations we need, so we swap it out immediately.

Third, we load environment variables from a `.env` file. This has to happen before anything tries to read config values.

Finally, we import the main classes - but notice `CodingAgent` uses a lazy import. It's not actually loaded until it's first used. This avoids a nasty circular import problem that we'll cover in a later video."

### Scene 1.2: Config Resolution (1:00 - 1:30)

> **[SCREEN: `cli.py` `main()` function, lines 116-257. Show a visual of three layers stacking.]**

"Now `main()` runs. Its first job is figuring out how to talk to the LLM.

Think of configuration like a sandwich with three layers. The bottom slice is your YAML config file - `.claraity/config.yaml` - with defaults like model name, temperature, and API URL. The middle layer is environment variables - these override the YAML. And the top layer is CLI arguments you typed - these override everything.

The function `resolve_llm_config()` at line 254 merges all three layers into one final config. If you passed `--model gpt-4` on the command line, that wins. Otherwise, it falls back to the env var, then the YAML."

### Scene 1.3: Agent Construction (1:30 - 2:15)

> **[SCREEN: `agent.py` `__init__()`, lines 178-432. Show components appearing one by one on the architecture diagram as they're mentioned.]**

"Now comes the heavy lift: building the `CodingAgent`. This constructor at line 178 of `agent.py` creates over 15 components. Let me walk through the most important ones.

Think of the agent as a company with departments:

**The Communications Department** - the LLM Backend. It handles all API calls to whatever model you're using - OpenAI, Ollama, Anthropic. Created at line 238.

**The Records Department** - the MemoryManager at line 268. It manages what the agent remembers: recent conversation, past sessions, semantic search, even file-based memories from your project's `.agent_memory` folder.

**The Toolshed** - the ToolExecutor at line 318, with `_register_tools()` at line 573 bolting on 25+ tools. File read, file write, code search, git operations, web search, task management - every capability the agent has comes from a registered tool.

**Security** - the PermissionManager at line 352 and ToolGatingService at line 360. Every single tool call passes through a 4-checkpoint security gate before it can execute. We'll deep-dive on this in Video 6.

**Special Operations** - the SpecialToolHandlers at line 370. Three tools - clarify, plan approval, and director checkpoints - are special because they pause the entire agent to ask the user a question.

**Talent Acquisition** - the SubAgentManager at line 381. The agent can spawn child agents to handle subtasks in parallel."

### Scene 1.4: Session Wiring + TUI Launch (2:15 - 2:30)

> **[SCREEN: `cli.py` `chat_mode()`, lines 40-107]**

"With the agent built, `chat_mode()` wires it into a session. A unique session ID is generated, a MessageStore is created for in-memory state, a SessionWriter is set up for JSONL persistence, and the TUI - our Textual-based terminal interface - is constructed and launched.

Think of the MessageStore as a whiteboard in a conference room. Everyone in the meeting can see it, but only one person - the MemoryManager - is allowed to write on it. The SessionWriter watches the whiteboard and copies everything to a permanent notebook. The TUI watches the whiteboard and puts it on the big screen.

When `app.run()` is called at line 107, Textual takes over. It builds the widget tree - conversation area, input box, status bar - and focuses the cursor.

The factory is open. Time for the first order."

---

## ACT 2: USER SENDS A MESSAGE - "The Order Comes In" (2:30 - 3:30)

> **[SCREEN: TUI with user typing "fix the null check bug in auth.py" and pressing Enter]**

**NARRATION:**

"The user types a message and presses Enter. What happens next is a relay race through four handoffs."

### Scene 2.1: Input to Worker (2:30 - 3:00)

> **[SCREEN: `app.py` `on_input_submitted_message`, line 1445. Highlight the key steps.]**

"The ChatInput widget posts an `InputSubmittedMessage` - a Textual message object carrying the user's text. The handler at line 1445 catches it.

First, it does guard checks. Is the text empty? Are we already streaming a response? Is the agent even configured? If any of these fail, bail out.

Then something clever happens at line 1517: the TUI **immediately mounts a UserMessage widget** - before the store even knows about it. This gives instant visual feedback. The user sees their message appear the moment they hit Enter, not after a round-trip through the persistence system.

Finally, at line 1534, it launches a **Textual worker**:

```python
self._stream_worker = self.run_worker(
    self._stream_response(user_input, attachments),
    exclusive=True,
)
```

This is non-blocking. The TUI event loop keeps running - the screen can refresh, the user can press Ctrl+C - while the agent works in the background."

### Scene 2.2: The Worker Chain (3:00 - 3:30)

> **[SCREEN: Flow diagram: `_stream_response` → `_process_stream` → `stream_handler` → `agent.stream_response()`]**

"`_stream_response` at line 1854 sets up the streaming state - disables the input box, updates the status bar. Then it calls `_process_stream`.

`_process_stream` at line 1983 is where the magic bridge happens. It calls `stream_handler`, which is a closure wrapping `agent.stream_response()`. This returns an **async generator** - a special Python object that produces values one at a time, on demand.

The TUI then enters a loop:

```python
async for event in event_stream:
    await asyncio.sleep(0)          # Yield to Textual
    await self._handle_event(event)  # Process the event
```

That `asyncio.sleep(0)` on line 2003 looks like it does nothing, but it's critical. Remember, Python is single-threaded. This line is like a polite person in conversation - after each sentence, they pause and say 'your turn.' Without it, the agent would monopolize the thread. Keyboard events would queue up. Ctrl+C wouldn't register. The screen wouldn't refresh. The TUI would appear frozen.

With it, after every single event from the agent, the TUI gets a chance to breathe - check for keyboard input, refresh the screen, process widget updates."

---

## ACT 3: THE AGENT CORE - "The Chef in the Kitchen" (3:30 - 6:30)

> **[SCREEN: `agent.py` `stream_response`, line 1023]**

**NARRATION:**

"Now we're inside `stream_response` - the 1,100-line async generator that IS the agent. Everything else is supporting cast. This function is the main character.

Think of it as a chef in a kitchen. The chef gets an order (user message), checks the recipe book (builds context), cooks the dish (calls the LLM), and if the recipe says 'chop onions first' (tool calls), the chef does that, then checks back with the recipe for the next step. When there are no more steps, the dish is served."

### Scene 3.1: Storing the Message (3:30 - 3:45)

> **[SCREEN: `agent.py` lines 1082-1110]**

"First, the agent stores the user's message via `memory.add_user_message()` at line 1093. This writes to the MessageStore - our single source of truth. That write triggers a store notification, which the SessionWriter picks up and persists to JSONL.

Then it parses any `@file.py` references, yields a `StreamStart` event, and moves to the most important setup step..."

### Scene 3.2: Context Assembly - "Packing the Briefcase" (3:45 - 4:30)

> **[SCREEN: `context_builder.py` `build_context()`, line 180. Show a visual of a briefcase being packed with labeled folders.]**

"Before calling the LLM, the agent has to assemble everything the LLM needs to see. Think of it as packing a briefcase before a big meeting.

`build_context()` at line 180 of `context_builder.py` constructs a list of messages in OpenAI format. Here's what goes in, and in what order:

**Folder 1: Your Role Description** - the system prompt. This is the long instruction set that tells the LLM 'you are a coding agent, here are your capabilities, here are the rules.' If plan mode or director mode is active, additional instructions get injected here. Any project-specific knowledge base content gets appended too.

**Folder 2: Reference Materials** - if the user wrote `@auth.py` in their message, the contents of that file go here in a `<referenced_files>` block. If RAG is enabled, relevant code snippets from vector search go in a `<relevant_code>` block.

**Folder 3: Your To-Do List** - active tasks and any continuation state from prior tool execution.

**Folder 4: The Full Meeting Notes** - the conversation history. Every user message, every assistant response, every tool call and result. This comes from the MessageStore - the complete timeline of this session.

The result is a Python list of dicts - the exact format the OpenAI API expects. This list IS the agent's entire reality. Everything it knows, everything it can reference, is in this list."

### Scene 3.3: The Tool Loop - "The Heartbeat" (4:30 - 6:00)

> **[SCREEN: The tool loop diagram from the lifecycle doc. Animate the flow as each step is narrated.]**

"Now we enter the tool loop at line 1150. This `while True` loop is the heartbeat of the agent. It's what separates an agent from a chatbot. A chatbot calls the LLM once and shows you the response. An agent calls the LLM, sees that it wants to take action, executes that action, feeds the result back, and calls the LLM again. It keeps going until the LLM says 'I'm done, here's my final answer.'

Each iteration has the same rhythm:

**Step 1: Budget check.** Are we over 200 tool calls? 50 iterations? Has the user pressed Ctrl+C? If any budget is exceeded, the agent pauses and asks the user: continue or stop?

**Step 2: Call the LLM.** At line 1251:

```python
llm_stream = self.llm.generate_provider_deltas_async(
    messages=current_context,
    tools=self._get_tools(),
    tool_choice='auto'
)
```

This fires an HTTP POST to the LLM provider. The response comes back as a stream of small chunks called `ProviderDeltas` - each carrying a few characters of text or a piece of a tool call.

**Step 3: Process the stream.** At line 1261, we iterate the deltas. Each text chunk gets yielded as a `TextDelta` event back to the TUI - this is the live text you see appearing character by character. Simultaneously, each delta feeds into the `StreamingPipeline`, which parses code blocks, accumulates tool calls, and eventually builds a complete structured `Message`.

**Step 4: Check for tool calls.** At line 1500, we check: did the LLM request any tool calls? If not - just text - we `break`. The response is complete. The chef's done. Serve the dish.

**Step 5: Execute tools.** If there ARE tool calls, we loop through each one. But before executing anything, every tool call passes through the **gating system**."

### Scene 3.4: The 4-Gate Security Check (5:15 - 5:45)

> **[SCREEN: `tool_gating.py` `evaluate()`, line 250. Show an airport security visual with 4 checkpoints.]**

"Think of tool gating like airport security with four checkpoints. Every tool call must pass all four:

**Checkpoint 1 - Repeat Detection.** Has this exact tool call - same name, same arguments - already failed? If so, blocked. We don't let the agent bang its head against the same wall. It gets a message saying 'this was blocked, try a different approach.'

**Checkpoint 2 - Plan Mode Gate.** Is the agent in planning mode? Then write operations like `edit_file` and `run_command` are denied. Planning means thinking, not doing.

**Checkpoint 3 - Director Gate.** Is the agent in a phased workflow where certain tools are restricted for the current phase? If so, denied.

**Checkpoint 4 - Approval Gate.** Is this a risky tool that needs user permission? In normal mode, tools like `write_file`, `edit_file`, and `run_command` need a thumbs-up from the user before executing.

If approval is needed, the agent pauses. It yields a pause event to the TUI, which shows an approval widget. The async generator literally suspends - it's sitting at an `await` statement, doing nothing, until the user clicks Approve or Reject. When they do, the UIProtocol resolves the waiting future, the generator wakes up, and processing continues."

### Scene 3.5: Context Update and Loop Back (5:45 - 6:15)

> **[SCREEN: `stream_phases.py`, showing `build_assistant_context_message` and `inject_controller_constraint`]**

"After all tool calls in an iteration are processed, the context gets updated for the next LLM call.

The assistant's response - text plus any tool calls it made - gets appended to the context. The tool results get appended too. And if any calls were blocked by gating, a special `[CONTROLLER]` message is injected telling the LLM: 'these calls were blocked, here's why, please try a different approach.'

Then we loop back to step 1 and call the LLM again - now with the full history of what it said, what tools ran, and what results came back. The LLM sees this enriched context and decides what to do next.

This loop typically runs 3-8 iterations for a typical coding task. Read a file, edit it, run tests, maybe fix a test failure, done."

### Scene 3.6: Stream End (6:15 - 6:30)

> **[SCREEN: `agent.py` line 2182, then back to the TUI]**

"When the LLM produces a response with no tool calls, the loop breaks. The agent yields `StreamEnd()`. Back in the TUI, `_stream_response`'s finally block runs: it flushes any buffered text to the screen, finalizes the message widget, resets the streaming state, and re-enables the input box.

The cursor blinks again. Ready for the next message."

---

## ACT 4: STREAMING AND PERSISTENCE - "Two Reporters, One Story" (6:30 - 8:00)

> **[SCREEN: Split screen showing the two paths - left side "Live Path", right side "Persistence Path"]**

**NARRATION:**

"I glossed over something important in the tool loop: there are two parallel paths for the LLM's response. Understanding why is key to understanding this architecture.

Imagine a courtroom. There are two people transcribing everything the witness says.

**Reporter 1** is the live stenographer. They type every word as it's spoken, projecting it on a screen in real-time. Fast, immediate, but raw - no structure, no formatting.

**Reporter 2** is the official court clerk. They listen to the same testimony, but they're organizing it: marking exhibits, noting objections, structuring it into an official record. Slower, but what they produce is the version that gets filed."

### Scene 4.1: Path 1 - Live Display (6:30 - 7:00)

> **[SCREEN: Code path: `ProviderDelta.text_delta` → `yield TextDelta` → `_handle_event` → `AssistantMessage` widget]**

"Path 1 is the live stenographer. Each `ProviderDelta` with a text chunk gets immediately yielded as a `TextDelta` event at line 1267 of `agent.py`. This flows up through the generator chain to `_handle_event` in the TUI.

But even here, there's a performance trick. The TUI doesn't render every single delta immediately - that would mean hundreds of screen updates per second. Instead, at line 2107, it buffers the text chunks and schedules a flush on a timer. So if 10 deltas arrive in 50 milliseconds, they get batched into one smooth screen update."

### Scene 4.2: Path 2 - Structured Persistence (7:00 - 7:30)

> **[SCREEN: Code path: `ProviderDelta` → `StreamingPipeline` → `Message` → `MessageStore` → `SessionWriter` + TUI notifications]**

"Path 2 is the court clerk. The same `ProviderDelta` also goes to `memory.process_provider_delta()` at line 1263. This feeds into the `StreamingPipeline` - the single canonical parser.

The pipeline doesn't just accumulate text. It detects code fences with regex, tracks thinking blocks, assembles tool call arguments from incremental deltas. When the stream finishes, it builds a complete `Message` object with typed segments - 'this part is text, this part is a code block, this part is a tool call reference.'

That message goes to `MessageStore.add_message()`. The store indexes it, assigns a sequence number, and notifies its subscribers.

Two subscribers are listening.

**Subscriber 1: the SessionWriter.** When it hears `MESSAGE_ADDED`, it immediately serializes the message to JSON and appends it to the JSONL file. When it hears `MESSAGE_FINALIZED`, it writes the final version. It intentionally skips `MESSAGE_UPDATED` events to reduce I/O - this is a conscious trade-off where a crash mid-stream would lose partial content but normal operation stays fast.

**Subscriber 2: the TUI's store subscription.** It handles `MESSAGE_ADDED` by mounting or adopting a widget. `MESSAGE_UPDATED` gets coalesced - batched on a timer so rapid updates don't thrash the screen. `MESSAGE_FINALIZED` flushes everything and marks the widget complete."

### Scene 4.3: Why Two Paths? (7:30 - 8:00)

> **[SCREEN: Side-by-side comparison of the two paths with characteristics listed]**

"You might ask: why not just use one path?

Path 1 alone wouldn't work for persistence. Raw text deltas have no structure - you can't save 'this is a code block' or 'this is tool call #3' from just a stream of characters.

Path 2 alone wouldn't work for display. The StreamingPipeline doesn't produce a result until the stream finishes. If we waited for it, the user would see nothing for seconds, then the entire response would appear at once. That's a terrible experience.

So both paths exist by design. Path 1 gives you instant gratification - text appears as the LLM thinks. Path 2 gives you structure and permanence - the session can be saved, loaded, and replayed with full fidelity.

They converge when the message finalizes: the store notification triggers the TUI to adopt the fully-structured message, replacing the raw streamed text with the properly parsed version."

---

## ACT 5: RECAP - "The Complete Map" (8:00 - 8:30)

> **[SCREEN: The full architecture diagram, with arrows animating the path of a message]**

**NARRATION:**

"Let's zoom out and see the full picture one more time.

User presses Enter. The TUI mounts the message immediately and launches a worker. The worker calls the agent's `stream_response` - an async generator. The agent stores the message, builds context - system prompt, history, files, RAG - and enters the tool loop.

Each iteration: call the LLM, stream the response back on two paths - live text to the screen, structured message to the store. If the LLM wants tools, each call passes through four security gates, gets executed, results feed back into context, and we loop again.

When the LLM has nothing more to say, the loop breaks, `StreamEnd` fires, the TUI finalizes everything, and the cursor blinks again."

---

## CLOSING (8:30 - 9:00)

> **[SCREEN: List of upcoming deep-dive videos]**

**NARRATION:**

"That's the complete lifecycle in 9 minutes. Every message you send to ClarAIty follows this exact path.

In the next videos, we'll zoom into the parts that deserve their own spotlight:

- **Video 2:** The Tool Loop - budgets, error recovery, and how the agent decides when to stop
- **Video 3:** Streaming Architecture - ProviderDeltas, the StreamingPipeline, and the dual-path design
- **Video 4:** Persistence and the Store - single writer, JSONL ledger, session replay
- **Video 5:** Context Building - what the LLM actually sees and how compaction works
- **Video 6:** The Permission and Gating System - how the agent stays safe

Thanks for watching. See you in the deep dive."

> **[SCREEN: End card]**

---

## PRODUCTION NOTES

### Screen Layout Suggestions
- **Code walkthrough scenes:** VS Code or similar editor on the left (70%), architecture diagram or flow visual on the right (30%)
- **Flow scenes:** Full-screen animated diagrams with boxes lighting up as narrated
- **TUI scenes:** Full-screen terminal recording (consider using asciinema or similar)

### Key Visuals to Prepare
1. **Architecture diagram** (from agent-lifecycle.md) - clean version with boxes and arrows
2. **Briefcase packing animation** for context assembly (5 labeled folders going in)
3. **Airport security checkpoint** visual for 4-gate gating
4. **Two reporters in courtroom** visual for dual-path streaming
5. **Factory assembly line** visual for startup
6. **Chef with recipe** visual for the tool loop

### Timing Guide
| Act | Duration | Content |
|-----|----------|---------|
| Cold Open | 0:30 | Hook - show the agent working |
| Act 1: Startup | 2:00 | Config, agent construction, TUI launch |
| Act 2: User Input | 1:00 | TUI handler chain, worker launch |
| Act 3: Agent Core | 3:00 | Context, tool loop, gating, execution |
| Act 4: Streaming | 1:30 | Dual path, store, persistence |
| Act 5: Recap | 0:30 | Full diagram walkthrough |
| Closing | 0:30 | Teaser for deep dives |
| **Total** | **~9:00** | |

### Code Files Referenced (in order of appearance)
1. `src/cli.py` - lines 9-34, 116-257, 40-107
2. `src/core/agent.py` - lines 178-432, 573-651, 1023-2182
3. `src/ui/app.py` - lines 1445-1539, 1854-2011, 2058-2167
4. `src/core/context_builder.py` - line 180
5. `src/core/tool_gating.py` - line 250
6. `src/core/stream_phases.py` - lines 22, 61
7. `src/llm/openai_backend.py` - line 1142
8. `src/core/streaming/pipeline.py` - line 87
9. `src/session/store/memory_store.py` - line 176
10. `src/session/persistence/writer.py` - lines 136, 185
