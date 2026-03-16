# Inline HTML vs React: Complete Gap Analysis

## Architecture Difference (Root Cause of Most Bugs)

**Inline HTML**: Builds UI imperatively. Everything inside a single `currentAssistantDiv` — text, tool cards, code blocks, thinking blocks, widgets all appended as siblings in chronological order. Store `message_added` events for main agent are **IGNORED** (line 3988: "Parent message_added: handled by stream events").

**React**: Renders declaratively from state. Messages, tool cards, subagent cards, and widgets rendered in **separate sections** in ChatHistory. Store `message_added` events are ALL processed, creating duplicate/leaked messages.

---

## Gap List

### GAP 1: Message rendering from store events (CRITICAL)
**Inline**: Ignores `message_added` for main agent. User messages rendered locally by `addMessage('user', ...)` on send. Assistant messages built from streaming events (`stream_start` → `text_delta` → `stream_end`). System messages never rendered.
**React**: Processes ALL `message_added` store events and renders them as chat bubbles.
**Symptoms**: System prompt leaks as visible bubble. User message appears twice (local `ADD_USER_MESSAGE` + store `MESSAGE_ADDED`). Project context visible in duplicate user message.
**Fix**: In reducer, ignore non-subagent `MESSAGE_ADDED`, `MESSAGE_UPDATED`, `MESSAGE_FINALIZED` events. Only process these when `subagent_id` is present (for subagent text inside SubagentCard).

### GAP 2: Tool card metadata caching (CRITICAL)
**Inline**: `toolMeta[call_id]` caches `tool_name` and `arguments` from the first event. Subsequent status updates use `meta.name || data.tool_name || 'tool'`.
**React**: Reducer overwrites `toolCards[call_id]` with each event's `data`. If a later event omits `tool_name`/`arguments`, they're lost.
**Symptoms**: Tool card shows "tool" with no name or arguments.
**Fix**: Merge incoming data with existing `toolCards[call_id]`, preserving previously-set fields.

### GAP 3: Chronological ordering of messages + tools (CRITICAL)
**Inline**: Tool cards are inserted INSIDE `currentAssistantDiv` as DOM siblings — between text paragraphs. Text before a tool is flushed with `renderMarkdown()`, tool card inserted, fresh `currentContentDiv` created after. Result: natural chronological flow.
**React**: ChatHistory renders all messages first, then all tool cards, then all subagent cards. The agent's response text after a subagent finishes appears ABOVE the subagent card.
**Symptoms**: Agent's response after subagent execution shows above the subagent card.
**Fix**: Need a unified timeline model. Each "turn" should be a sequence of segments (text → tool → text → subagent → text) rendered in order.

### GAP 4: Tool card inline insertion with text flush
**Inline**: Before inserting a tool card, calls `renderMarkdown()` to flush pending text, then appends the card, then creates a fresh `currentContentDiv` + resets `markdownBuffer`. Text after the tool renders BELOW it.
**React**: Streaming text accumulates in `markdownBuffer` and tool cards are in a separate section. No interleaving.
**Fix**: Part of GAP 3 solution — the timeline model needs to track when tools interrupt text flow.

### GAP 5: Subagent text routing
**Inline**: `message_added` with `subagent_id` → appends text inside `saInfo.body` as `.subagent-text` div. `message_updated` with `subagent_id` → updates that same div.
**React**: All `message_added` events (including subagent ones) go to the main `messages` array and render as top-level bubbles.
**Fix**: In reducer, route `MESSAGE_ADDED`/`MESSAGE_UPDATED` with `subagent_id` to a subagent-specific data structure, and render inside SubagentCard.

### GAP 6: Subagent container is nested inside delegation tool card
**Inline**: When `subagent:registered` fires, the subagent body (`<details>`) is appended INSIDE the parent `delegate_to_subagent` tool card. Child tool cards go inside `saInfo.body`. The subagent is visually a child of the delegation card.
**React**: SubagentCard is rendered as a separate top-level element after all messages and main tool cards.
**Fix**: SubagentCard rendering needs to be positioned at the point in the timeline where the delegation tool card appears.

### GAP 7: Session replay filtering
**Inline**: `renderSessionHistory()` (line 2402) explicitly skips system messages (line 2470: "// Skip system messages in replay"). Only renders user and assistant messages.
**React**: `REPLAY_MESSAGES` creates ChatMessage for every message including system role.
**Fix**: Filter out system messages in REPLAY_MESSAGES handler.

### GAP 8: Session replay tool card rendering
**Inline**: During replay, creates static tool cards from `msg.tool_calls` with name, args, "done" badge. Tool results update the parent card's badge if they indicate errors.
**React**: REPLAY_MESSAGES only creates message bubbles. No tool cards are reconstructed from replay data.
**Fix**: Parse `tool_calls` from replay messages and create static tool card entries.

### GAP 9: Code block rendering — flush and new content div
**Inline**: `startCodeBlock()` calls `flushAndNewContentDiv()`, renders code block as sibling, then `endCodeBlock()` creates fresh content div. Code blocks are inline within the assistant message.
**React**: Code blocks are rendered as separate state-driven components in ChatHistory, positioned after all messages.
**Fix**: Code blocks need to be part of the turn timeline (like tool cards).

### GAP 10: Thinking block rendering — same flush pattern
**Inline**: `startThinking()` calls `flushAndNewContentDiv()`, thinking block is a sibling, `endThinking()` creates fresh content div.
**React**: Thinking blocks rendered as separate component, positioned after all messages.
**Fix**: Same as GAP 9 — needs timeline integration.

### GAP 11: Interactive widgets inside assistant div
**Inline**: Pause widget, clarify widget, plan widget are all appended to `currentAssistantDiv`. They appear chronologically where they occurred.
**React**: These widgets are rendered at fixed positions in ChatHistory (after all tool cards).
**Fix**: Widgets need timeline positioning too.

### GAP 12: Turn stats inside assistant div
**Inline**: `showTurnStats()` appends stats div to `currentAssistantDiv` as last child.
**React**: TurnStats rendered at fixed position after undo bar.
**Fix**: Minor — can stay at bottom, but ideally part of the turn.

### GAP 13: Approval section cleanup on status change
**Inline**: When status moves away from `awaiting_approval`, hides the approval section (`approvalSection.style.display = 'none'`) and removes promoted widgets.
**React**: ToolCard conditionally renders approval buttons based on `data.status === "awaiting_approval"`, so this should work IF data is preserved (depends on GAP 2 fix).
**Status**: Should work after GAP 2 fix. Verify.

### GAP 14: Auto-open diff for write_file/edit_file on approval
**Inline**: When tool enters `awaiting_approval` state and is `write_file`/`edit_file`, immediately sends `showDiff` message using cached `meta.arguments`.
**React**: ToolCard has `useEffect` that triggers `handleShowDiff` when status transitions to `awaiting_approval`. Should work IF arguments are preserved (GAP 2).
**Status**: Should work after GAP 2 fix. Verify.

### GAP 15: Error messages as styled divs
**Inline**: `error` events create a red-colored div in chatHistory (line 3948-3953).
**React**: Reducer returns state unchanged for ERROR action (line 641: "Errors displayed via toast/notification, not state change"). Errors are silently dropped.
**Fix**: Either show errors as messages or add a toast/notification system.

### GAP 16: New session clears all state
**Inline**: When `sessionInfo` arrives with a different `sessionId`, clears ALL state: chatHistory, tool cards, tool meta, subagent containers, timers, todo panel, context bar, session stats.
**React**: `SET_SESSION_INFO` only updates connection fields. Does NOT clear messages, tool cards, subagents, etc.
**Fix**: Add session change detection. When sessionId changes, reset messages, toolCards, toolOrder, subagents, etc.

### GAP 17: Streaming indicator in send button
**Inline**: When streaming starts, send button changes to "Stop" (red background), click sends interrupt. On stream_end, reverts to "Send".
**React**: InputBox has separate send/interrupt state handling. Need to verify it works correctly.
**Status**: Likely works. Verify.

### GAP 18: insertAndSend handling
**Inline**: Sets chatInput.value to content, auto-resizes, and calls `sendMessage()` (which renders local user bubble + sends to server).
**React**: App.tsx directly calls `postMessage({ type: "chatMessage", content: msg.content })` without adding a local user message bubble.
**Fix**: Should also dispatch `ADD_USER_MESSAGE` before sending, or the user won't see their message until the store event comes back (which we're ignoring per GAP 1 fix).

### GAP 19: Subagent card visual — starts collapsed, auto-expands on approval
**Inline**: `details.open = false` on creation. Opens when child has `awaiting_approval`. Collapses on `unregistered`.
**React**: SubagentCard starts with `details open={info.active || hasAwaitingApproval}`. Active subagents are always expanded.
**Difference**: Minor behavioral difference. Inline starts collapsed, React starts open for active subagents.

### GAP 20: Context compacting display
**Inline**: `context_compacting` and `context_compacted` are in the switch but marked as handled (break with no action).
**React**: Same — these cases break with no action in `dispatchServerMessage`.
**Status**: Parity. OK.

---

## Priority Order for Fixing

### Phase A: Fundamental architecture fix (GAPs 1, 2, 3, 4, 5, 6, 9, 10, 11)
These are all interconnected. The core fix is a **turn-based timeline model**:
- A "turn" is a sequence of segments: `[text, tool, text, thinking, text, codeblock, text, subagent, text, widget]`
- Stream events build the current turn's segments
- Tool cards, thinking blocks, code blocks become segments within the turn
- ChatHistory renders turns in order, each turn renders its segments in order

### Phase B: Data integrity (GAPs 2, 7, 8, 16)
- Tool metadata merging in reducer
- System message filtering in replay
- Tool card reconstruction from replay data
- Session change state reset

### Phase C: Minor fixes (GAPs 12, 15, 18)
- Turn stats positioning
- Error message display
- insertAndSend local user message
