---
name: run_command cancellation -- end to end flow and interrupt architecture
description: VS Code Stop path, orphan tool result fixer, three cancellation message paths, VSCodeChannel trap, subprocess kill pattern, webview reducer stale-card finalization
type: feedback
---

## VS Code is the primary entry point, TUI is secondary

The VS Code extension (not the TUI) is the primary way users interact with ClarAIty Code.
Both entry points drive the same CodingAgent and the same tool implementations -- no behavioral divergence.

## VSCodeChannel is a dead end for run_command

VSCodeChannel (src/server/vscode_channel.py) exists as planned infrastructure for running commands
in a visible VS Code terminal panel. It is NOT wired to RunCommandTool. Do not revisit this path.

## VS Code Stop does TWO things simultaneously

When the user clicks Stop in VS Code, StdioServer.submit_action() (src/server/stdio_server.py:337):
1. Sets the interrupt flag via super().submit_action(action)
2. Hard-cancels the entire streaming asyncio Task via self._streaming_task.cancel()

The hard cancel (task.cancel()) preempts everything -- it raises CancelledError at the nearest
await point, before the interrupt poll loop in _execute_foreground_async gets a chance to fire.
The check_interrupted() poll loop only works reliably in TUI mode (no task.cancel()).

## What the LLM actually sees after mid-flight cancellation

When Stop is pressed while a tool is running, the tool call becomes an ORPHAN -- no matching
tool result is stored in the session before the task is cancelled. On the NEXT turn, when the
agent rebuilds LLM context, _fix_orphaned_tool_calls() (src/core/agent.py) synthesizes
a fake tool result for the orphan. THAT is the message the LLM sees -- not any in-flight
cancellation handler.

## Three cancellation message paths (know which fires when)

1. **Orphan fixer** (agent.py _fix_orphaned_tool_calls) -- fires on NEXT turn for any hard-cancelled tool.
   This is the path for VS Code Stop during a running tool. THE REAL ONE.
   Now correctly emits CoreToolStatus.CANCELLED (was ERROR before fix).

2. **Approval rejection** (agent.py, approval phase) -- fires when user explicitly rejects at the
   approval prompt (clicks Reject or Stop before approving). Message: "Tool call rejected by user"

3. **CancelledError handler** (agent.py, approval wait) -- fires during approval WAIT if task is
   cancelled while waiting for user to approve/reject. Rarely hits in practice for run_command.

## The interrupt poll loop exists but doesn't fire for VS Code Stop

_execute_foreground_async() (src/tools/file_operations.py) polls check_interrupted() every 0.2s.
This correctly kills the subprocess. But because task.cancel() also fires simultaneously, the
ToolResult returned by the handler becomes an orphan -- it never reaches the caller before the task dies.
The subprocess IS killed cleanly. The result just doesn't get filed via this path in VS Code mode.

When the poll loop DOES fire (check_interrupted=True) it returns ToolResult with metadata["interrupted"]=True,
status=ERROR. _process_parallel_tool_result() now checks this flag and emits CANCELLED instead of ERROR.

## Webview reducer: stale tool cards on stream_end

The VS Code webview reducer (reducer.ts STREAM_END case) finalizes any tool cards still
in 'running' or 'pending' state when the stream ends. Without the interrupted flag, it
marked them all as 'error'. Fix: StreamEnd event now carries interrupted:bool; when True,
stale cards become 'cancelled' instead of 'error'.

**Data flow for the flag:**
StreamEnd(interrupted=True) -> serialize_event() (asdict) -> wire as {type:"stream_end", interrupted:true}
-> dispatch.ts -> STREAM_END action {interrupted:true} -> reducer.ts uses 'cancelled' for stale cards.

## Windows process-tree kill

On Windows, plain process.terminate() leaves grandchild processes alive and pipes open.
Must use: taskkill /F /T /PID (same as BackgroundTaskRegistry._kill_process()).
On Unix: os.killpg(process.pid, signal.SIGKILL) to kill entire process group.
RunCommandTool._kill_process() (src/tools/file_operations.py) implements both correctly.

## Key lesson from this investigation

When debugging "wrong status shown in VS Code", there are TWO separate places that set the
status of a tool card:
1. Python: update_tool_state() in agent.py -- fires during execution
2. TypeScript: STREAM_END reducer in reducer.ts -- fires as a cleanup sweep when the stream ends

The reducer cleanup can OVERRIDE whatever Python emitted. Always check both when debugging
tool card status issues.
