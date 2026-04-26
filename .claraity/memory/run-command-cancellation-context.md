---
name: run_command cancellation -- end to end flow and interrupt architecture
description: VS Code Stop path, orphan tool result fixer, three cancellation message paths, VSCodeChannel trap, subprocess kill pattern
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
agent rebuilds LLM context, _fix_orphaned_tool_calls() (src/core/agent.py:1327) synthesizes
a fake tool result for the orphan. THAT is the message the LLM sees -- not any in-flight
cancellation handler.

**The fix:** Change the synthetic message at agent.py:1333 (not the approval rejection or
CancelledError paths). Currently: "Tool call was interrupted."

## Three cancellation message paths (know which fires when)

1. **Orphan fixer** (agent.py:1333) -- fires on NEXT turn for any hard-cancelled tool.
   This is the path for VS Code Stop during a running tool. THE REAL ONE.

2. **Approval rejection** (agent.py:2353) -- fires when user explicitly rejects at the
   approval prompt (clicks Reject or Stop before approving). Message: "Tool call rejected by user"

3. **CancelledError handler** (agent.py:2408) -- fires during approval WAIT if task is
   cancelled while waiting for user to approve/reject. Message: "Tool call cancelled by user
   (stream interrupted)". Rarely hits in practice for run_command.

## The interrupt poll loop exists but doesn't fire for VS Code Stop

_execute_foreground_async() (src/tools/file_operations.py) polls check_interrupted() every 0.2s.
This correctly kills the subprocess (confirmed by logs: "RunCommandTool: hard cancel --
terminating subprocess"). But because task.cancel() also fires, the ToolResult returned by
the handler becomes an orphan -- it never gets filed before the task dies.
The subprocess IS killed cleanly. The result just doesn't reach the LLM via this path.

## Windows process-tree kill

On Windows, plain process.terminate() leaves grandchild processes alive and pipes open.
Must use: taskkill /F /T /PID (same as BackgroundTaskRegistry._kill_process()).
On Unix: os.killpg(process.pid, signal.SIGKILL) to kill entire process group.
RunCommandTool._kill_process() (src/tools/file_operations.py) implements both correctly.

## Wiring points for RunCommandTool UIProtocol

set_ui_protocol() is called post-registration in two places:
- src/server/stdio_server.py wire_delegation_tool() -- VS Code path
- src/ui/subagent_coordinator.py setup_registry() -- TUI path

## Key lesson from this investigation

When debugging "wrong message shown to LLM", find the exact line that produces the string
first (grep for it) before tracing execution flow. We spent significant time in asyncio
internals before finding agent.py:1333 which was the actual source of "Tool call rejected
by user." -- a one-line fix.
