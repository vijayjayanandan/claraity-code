# Lessons Learned: 35 Bugs That Almost Shipped

A guide to VS Code extension and React webview development, taught through real bugs found in the ClarAIty codebase. Each lesson uses an analogy to explain *why* it matters, then shows the actual code that was wrong and how it was fixed.

Use this as a checklist for your own extensions. If you see yourself in any of these patterns, fix it before your users find it.

---

## Table of Contents

1. [The House of Cards (No Error Boundary)](#1-the-house-of-cards)
2. [The Silent Postman (Fire-and-Forget Messages)](#2-the-silent-postman)
3. [The Zombie Process (No Auto-Restart)](#3-the-zombie-process)
4. [The Infinite Scroll of Doom (Unbounded Memory)](#4-the-infinite-scroll-of-doom)
5. [The Lying Thermometer (Stub Code in Production)](#5-the-lying-thermometer)
6. [The Case-Blind Librarian (Path Sensitivity)](#6-the-case-blind-librarian)
7. [The Spinning Beach Ball (No Timeout Detection)](#7-the-spinning-beach-ball)
8. [The Frozen Dashboard (Stuck Streaming)](#8-the-frozen-dashboard)
9. [The Phantom Package (Missing Build Step)](#9-the-phantom-package)
10. [The Haunted Dice (Impure Reducer)](#10-the-haunted-dice)
11. [The Unlocked Back Door (Type Safety Bypass)](#11-the-unlocked-back-door)
12. [The Leaky Faucet (Memory Leaks)](#12-the-leaky-faucet)
13. [The Broken Telephone (No Message Validation)](#13-the-broken-telephone)
14. [The One-Way Mirror (Approve Before Review)](#14-the-one-way-mirror)
15. [The Confused Liar (Wrong State After Cancel)](#15-the-confused-liar)
16. [The Sluggish Painter (Missing React.memo)](#16-the-sluggish-painter)
17. [The Nested Loop Tax (O(n*m) Lookup)](#17-the-nested-loop-tax)
18. [The Passwordless Wifi (API Key Exposure)](#18-the-passwordless-wifi)
19. [The Unlabeled Buttons (Missing Accessibility)](#19-the-unlabeled-buttons)
20. [The Permanent Sticky Note (Diff Content Leak)](#20-the-permanent-sticky-note)
21. [The Time Bomb Timer (setTimeout Without Cleanup)](#21-the-time-bomb-timer)
22. [The Invisible Error (No Build Fallback)](#22-the-invisible-error)
23. [The Narrow Funnel (DOMPurify Default Config)](#23-the-narrow-funnel)
24. [The Sticky Settings Panel (Auto-Close UX)](#24-the-sticky-settings-panel)
25. [The Copy-Paste Bomb (No Input Size Limit)](#25-the-copy-paste-bomb)
26. [The Nuclear Undo (Destructive Splice)](#26-the-nuclear-undo)
27. [The Goldfish Memory (Small Undo History)](#27-the-goldfish-memory)
28. [The Invisible Badge (Poor Color Contrast)](#28-the-invisible-badge)
29. [The Key Collision (Shortcut Conflicts)](#29-the-key-collision)
30. [The Orphaned Child (Fire-and-Forget Shutdown)](#30-the-orphaned-child)
31. [The Growing Logbook (Unbounded Set)](#31-the-growing-logbook)
32. [The Minified Mystery (No Production Sourcemaps)](#32-the-minified-mystery)
33. [The Future-Proof Trap (Aggressive Build Target)](#33-the-future-proof-trap)
34. [The Injection Needle (String Interpolation in Shell)](#34-the-injection-needle)
35. [The Ghost Setting (Dead Code Reference)](#35-the-ghost-setting)

---

## 1. The House of Cards

**Category:** React | **Severity:** Critical

### The Analogy

Imagine a 50-story building with no fire escapes. Every floor is connected — if one floor catches fire, the entire building collapses and everyone is trapped inside a blank white void. That's what happens when a React app has no Error Boundary. One bad render in one component takes down the entire UI with zero recovery path.

### The Problem

The ClarAIty webview had no `ErrorBoundary` wrapping the root `<App />` component. When the agent sent malformed data — say, a tool card with a `null` name — a component would throw during render, React would unmount the entire tree, and the user would see a completely blank white panel. No error message, no reload button, no way to recover without reloading VS Code.

```tsx
// main.tsx — BEFORE: no safety net
createRoot(rootEl).render(
  <StrictMode>
    <App />       {/* If this throws, blank white screen */}
  </StrictMode>,
);
```

### The Fix

We added an `ErrorBoundary` class component that catches render errors and displays a recovery UI:

```tsx
// main.tsx — AFTER: graceful degradation
createRoot(rootEl).render(
  <StrictMode>
    <ErrorBoundary>   {/* Catches errors, shows "Reload" button */}
      <App />
    </ErrorBoundary>
  </StrictMode>,
);
```

The `ErrorBoundary` itself uses `getDerivedStateFromError` and `componentDidCatch` to catch the error, log it, and render a friendly "Something went wrong — Reload" fallback.

### The Lesson

> **Every React app that runs in an environment the user can't easily refresh (VS Code webview, Electron, mobile) MUST have an Error Boundary at the root.** It's the difference between "oops, click to retry" and "the entire tool is broken, restart the application."

---

## 2. The Silent Postman

**Category:** Connection | **Severity:** Critical

### The Analogy

You hand a letter to a postman. He walks away. You never hear back. Did the letter arrive? Did the recipient read it? Is the postman even alive? You have no idea — you just keep writing more letters into the void. That's what happened when ClarAIty sent messages to a dead agent process.

### The Problem

The `send()` method in `StdioConnection` wrote to the child process's stdin pipe with no error handling and no delivery confirmation:

```typescript
// BEFORE: fire and forget
send(message: ClientMessage): void {
    if (this.process?.stdin && !this.process.stdin.destroyed) {
        const line = JSON.stringify(wrapped) + '\n';
        this.process.stdin.write(line);   // <-- No error callback!
    } else {
        this.logLine('[STDIO] Cannot send: process not running');
        // ^^ Just logs. The webview never finds out.
    }
}
```

When the agent crashed, the user would type messages that appeared in the chat (local state update), but the agent never responded. No error, no feedback — a silent black hole.

### The Fix

We added three layers of feedback:

1. **Write error callback** — detects broken stdin pipe immediately
2. **Dead process detection** — fires an error event when send() is called on a dead process
3. **Auto-restart trigger** — attempts to bring the agent back

```typescript
// AFTER: detect failures and recover
send(message: ClientMessage): void {
    if (this.process?.stdin && !this.process.stdin.destroyed) {
        this.process.stdin.write(line, (err) => {
            if (err) {
                // Pipe is broken — agent is dead
                this._onMessage.fire({
                    type: 'error',
                    user_message: 'Lost connection to agent. Attempting to restart...',
                });
                this.maybeAutoRestart('stdin write error');
            }
        });
    } else {
        // Tell the webview immediately
        this._onMessage.fire({
            type: 'error',
            user_message: 'Agent is not running. Attempting to restart...',
        });
        this.maybeAutoRestart('process not running on send');
    }
}
```

### The Lesson

> **Never fire-and-forget messages to an external process.** Always handle the write callback, always have a "what if the other side is dead?" path, and always tell the user what happened.

---

## 3. The Zombie Process

**Category:** Connection | **Severity:** Critical

### The Analogy

You hire a contractor. They show up, start working, and one day they just... stop. They don't quit, they don't call — they're just gone. But you don't hire a replacement because technically they're "still employed." Months later you realize nothing has been built since they disappeared. That's what happened when the ClarAIty agent process crashed.

### The Problem

When the Python agent exited unexpectedly, the extension showed "ClarAIty (offline)" in the status bar and... that was it. The user had to **reload the entire VS Code window** to get the agent back. Production extensions like Pylance, ESLint, and rust-analyzer all auto-restart their language servers.

```typescript
// BEFORE: one death = permanent death
conn.onDisconnected(() => {
    statusBar.text = '$(sparkle) ClarAIty (offline)';
    statusBar.tooltip = 'ClarAIty - Disconnected';
    // User must reload VS Code window. No recovery path.
});
```

### The Fix

We added auto-restart with exponential backoff — 3 attempts at 2s, 4s, 8s intervals:

```typescript
// AFTER: resilient reconnection
private maybeAutoRestart(reason: string): void {
    if (this._disposed || this._intentionalDisconnect) return;

    if (this._restartCount >= MAX_RESTART_ATTEMPTS) {
        // Show "Restart" button after 3 failures
        vscode.window.showErrorMessage(
            `ClarAIty agent stopped unexpectedly. Click "Restart" to try again.`,
            'Restart',
        ).then((choice) => {
            if (choice === 'Restart') this.restart();
        });
        return;
    }

    this._restartCount++;
    const delay = 2000 * Math.pow(2, this._restartCount - 1);
    setTimeout(() => this.connect(), delay);
}
```

The status bar now shows "reconnecting..." during retry and "offline" only after all attempts fail.

### The Lesson

> **Any external process your extension depends on WILL crash eventually.** OOM, unhandled exceptions, OS signals — it's a matter of when, not if. Build auto-restart with backoff from day one. Your users should never need to know the process died.

---

## 4. The Infinite Scroll of Doom

**Category:** Memory | **Severity:** Critical

### The Analogy

Imagine a chat app that never deletes old messages from RAM. After a year of chatting, your phone runs out of memory and crashes. That's exactly what happened with the webview's timeline. Every message, every tool card, every thinking block was kept in an ever-growing JavaScript array — forever.

### The Problem

The `timeline[]` array, `toolCards{}` record, and `messages[]` array all grew without any limit:

```typescript
// In the reducer — arrays grow forever
timeline: [...state.timeline, newEntry],    // Never trimmed
toolCards: { ...state.toolCards, [id]: tc }, // Never cleaned up
messages: [...state.messages, msg],         // Never capped
```

After 200+ turns with tools, the webview (a Chromium renderer process with ~512MB limit) would accumulate hundreds of thousands of DOM nodes and megabytes of string data, eventually crashing.

### The Fix

We added a `trimTimeline` function that caps the timeline at 500 entries and cleans up associated data:

```typescript
const MAX_TIMELINE_ENTRIES = 500;

function trimTimeline(state: AppState): AppState {
    if (state.timeline.length <= MAX_TIMELINE_ENTRIES) return state;

    const excess = state.timeline.length - MAX_TIMELINE_ENTRIES;
    const removed = state.timeline.slice(0, excess);
    const trimmed = state.timeline.slice(excess);

    // Clean up toolCards for removed tool entries
    const removedCallIds = new Set<string>();
    for (const entry of removed) {
        if (entry.type === "tool") removedCallIds.add(entry.callId);
    }
    // ... filter toolCards and toolOrder ...

    return { ...state, timeline: trimmed, toolCards, toolOrder, messages };
}
```

This runs after every `STREAM_END` and `REPLAY_MESSAGES` — the two points where batches of entries settle.

### The Lesson

> **Every collection in a long-running application needs a size limit.** Arrays, maps, sets, caches — if they can grow, they will grow, and eventually they'll eat all available memory. Set explicit caps and implement eviction from the start.

---

## 5. The Lying Thermometer

**Category:** Reliability | **Severity:** Critical

### The Analogy

Imagine a thermometer that always reads 72 degrees. Freezing outside? 72 degrees. House on fire? 72 degrees. That's what the TerminalQueue was doing — every command was reported as a success (exit code 0) regardless of what actually happened.

### The Problem

The `waitForCommandCompletion` method was a stub that hardcoded success after 1 second:

```typescript
// BEFORE: the most dangerous TODO in production
private waitForCommandCompletion(...): Promise<{ exitCode: number; output: string }> {
    return new Promise((resolve, reject) => {
        const checkInterval = setInterval(() => {
            // Simplified: assume command finished after a short delay
            // In production, you'd parse terminal output for "EXIT_CODE:" marker
            // For MVP, just wait 1 second per 10 seconds of timeout
            if (elapsed > 1000) {
                clearInterval(checkInterval);
                resolve({ exitCode: 0, output: '[Command executed]' });
                //              ^^^^ ALWAYS ZERO. ALWAYS "SUCCESS."
            }
        }, 100);
    });
}
```

This meant: failed builds appeared as passing, broken tests showed as green, and any command-based workflow gave the agent completely wrong feedback.

### The Fix

We replaced the entire `TerminalQueue` (which used `terminal.sendText()`) with a `CommandExecutor` that uses `child_process.exec` — which natively captures exit codes, stdout, and stderr:

```typescript
// AFTER: real exit codes, real output
class CommandExecutor {
    private executeCommand(...): Promise<void> {
        return new Promise<void>((resolve) => {
            const child = exec(command, { cwd, timeout, shell }, (error, stdout, stderr) => {
                const exitCode = error ? (error as any).code ?? 1 : 0;
                const output = stdout + (stderr ? '\n[stderr]\n' + stderr : '');
                this.onResult(taskId, exitCode, output, error ? error.message : '');
                resolve();
            });
            child.stdin?.end(); // Prevent stdin inheritance deadlock
        });
    }
}
```

### The Lesson

> **Never ship stub implementations in production code paths.** If a function can't do what it claims, make it fail loudly (throw, return an error) rather than silently succeed. A function that lies about its results is worse than one that crashes — at least a crash is honest.

---

## 6. The Case-Blind Librarian

**Category:** Cross-Platform | **Severity:** Critical

### The Analogy

A librarian who files books alphabetically but treats "Apple" and "apple" as the same book. On the Windows shelf this works fine (Windows is case-insensitive). But on the Linux/Mac shelf, "Apple" and "apple" are completely different books. Now the wrong book gets checked out, returned to the wrong slot, or lost entirely.

### The Problem

Three components all normalized file paths with `.toLowerCase()`:

```typescript
// code-lens-provider.ts, undo-manager.ts, file-decoration-provider.ts
const normalized = filePath.replace(/\\/g, '/').toLowerCase();
//                                                ^^^^^^^^^^^^
// On Linux: /src/MyComponent.tsx and /src/mycomponent.tsx are DIFFERENT files
// After toLowerCase: both become /src/mycomponent.tsx — COLLISION
```

This meant: Accept/Reject CodeLens could appear on the wrong file, undo could restore the wrong file, and the "AI" badge could mark the wrong file in the explorer.

### The Fix

We created a platform-aware normalization function:

```typescript
function normalizePath(p: string): string {
    const fwd = p.replace(/\\/g, '/');
    return process.platform === 'win32' ? fwd.toLowerCase() : fwd;
}
```

Only lowercase on Windows (where the filesystem is case-insensitive). Keep original case on Linux/Mac.

### The Lesson

> **File paths are case-sensitive on Linux and macOS.** If you're building a cross-platform tool, never call `.toLowerCase()` on paths unless you're explicitly on Windows. Use `process.platform` to decide. This is one of the most common cross-platform bugs in Node.js applications.

---

## 7. The Spinning Beach Ball

**Category:** UX | **Severity:** Important

### The Analogy

You ask someone a question. They stare at you blankly. You wait 30 seconds. A minute. Five minutes. Are they thinking? Did they hear you? Did they have a stroke? You have no idea because there's no feedback. That's what happened when the agent was hung — the user sent a message and got infinite silence.

### The Problem

After sending a `chat_message`, nothing checked whether the agent actually responded. If the agent was hung (infinite loop, deadlocked on stdin, etc.), the user saw their message appear but got no streaming, no error, no timeout — just eternal silence.

### The Fix

We added a 30-second response timeout:

```typescript
private startResponseTimeout(): void {
    this._responseTimer = setTimeout(() => {
        this._onMessage.fire({
            type: 'error',
            error_type: 'response_timeout',
            user_message: `Agent did not respond within 30 seconds. It may have crashed.`,
        });
    }, 30_000);
}

// Cleared when any response arrives (stream_start, text_delta, error)
```

### The Lesson

> **Every request to an external system needs a timeout.** HTTP requests have timeouts. Database queries have timeouts. Your IPC messages should too. The question isn't "will the other side hang?" — it's "how quickly will the user know?"

---

## 8. The Frozen Dashboard

**Category:** State Management | **Severity:** Important

### The Analogy

You're watching a live sports scoreboard. The connection drops mid-game. But the scoreboard doesn't show "disconnected" — it just freezes on the last score, with the "LIVE" indicator still blinking. You think the game is still being played. Hours later you realize you've been staring at a frozen screen. That's what happened when the connection dropped during streaming.

### The Problem

If the agent process died mid-stream, the webview's `isStreaming` stayed `true` forever. The spinning indicator kept spinning, the "Stop" button did nothing (process was already dead), and the user had no indication that anything was wrong.

### The Fix

When the connection status changes to "disconnected" while streaming is active, we force-end the stream and show an error:

```tsx
// App.tsx — connection status handler
case "connectionStatus": {
    const nowConnected = msg.status === "connected";
    dispatch({ type: "SET_CONNECTED", connected: nowConnected });

    // Recovery: if connection drops during active stream, end it
    if (wasConnected && !nowConnected && state.isStreaming) {
        dispatch({ type: "STREAM_END" });
        dispatch({
            type: "ERROR",
            message: "Connection to agent lost during streaming.",
        });
    }
    break;
}
```

### The Lesson

> **UI state must be consistent with system state.** If the backend connection dies, the UI must reflect that immediately. Never let the UI stay in a "working" state when the underlying system has failed. This is especially important for streaming/real-time interfaces.

---

## 9. The Phantom Package

**Category:** Build & Packaging | **Severity:** Critical

### The Analogy

You ship a product box with the instruction manual but forget to include the actual product. The box looks correct, the label is right, but when the customer opens it — empty. That's what happened when `vsce package` was run: the extension bundle was built, but the React webview was not.

### The Problem

The `vscode:prepublish` script only built the extension host code:

```json
// BEFORE: webview build missing from publish pipeline
"vscode:prepublish": "npm run build",
"build": "node esbuild.mjs --production",
// ^^ Only builds src/extension.ts → out/extension.js
// The React webview (webview-ui/dist/webview.js) is NOT built
```

If someone ran `vsce package` without manually running the webview build first, the published `.vsix` would ship with stale or missing webview assets. Users would get a blank panel with a JavaScript 404 error.

### The Fix

Two-part fix: (a) build webview before extension, and (b) detect missing build at runtime:

```json
// AFTER: complete build pipeline
"vscode:prepublish": "npm run build:webview && npm run build",
```

```typescript
// Runtime fallback if build is missing
if (!fs.existsSync(scriptFsPath)) {
    return `<html><body>
        <h3>ClarAIty: Webview not built</h3>
        <p>Run: <code>cd webview-ui && npm run build</code></p>
    </body></html>`;
}
```

### The Lesson

> **Your CI/publish pipeline must build ALL artifacts, not just the ones you think of.** If your extension has a separate webview build step, it MUST be in `vscode:prepublish`. Test your packaging by running `vsce package` from a clean state and verifying the vsix contents.

---

## 10. The Haunted Dice

**Category:** React State | **Severity:** Critical

### The Analogy

Imagine rolling a die where the result depends on how many times you've rolled it before — including in parallel universes. In React 18 StrictMode, reducers run twice in development to catch impure functions. If your reducer has side effects (like incrementing a counter), the second run produces different results. You've got haunted dice.

### The Problem

The reducer used module-level mutable variables for timeline IDs:

```typescript
// BEFORE: mutable state outside the reducer (impure!)
let timelineCounter = 0;   // Mutated inside reducer
let sessionNonce = 0;       // Mutated inside reducer

function timelineId(prefix: string): string {
    return `${prefix}-${++timelineCounter}-${sessionNonce}`;
    //                   ^^ Side effect! Reducer is no longer pure.
}
```

In React 18 StrictMode, the reducer runs twice per action in development. Each run increments `timelineCounter`, so the second pass produces different IDs — leading to ghost timeline entries, key collisions, and unpredictable state.

### The Fix

We moved the counters into `AppState` and made ID generation return `[id, updatedState]`:

```typescript
// AFTER: counters in state, reducer is pure
interface AppState {
    timelineCounter: number;
    sessionNonce: number;
    // ...
}

function nextTimelineId(state: AppState, prefix: string): [string, AppState] {
    const counter = state.timelineCounter + 1;
    return [
        `${prefix}-${counter}-${state.sessionNonce}`,
        { ...state, timelineCounter: counter },
    ];
}
```

### The Lesson

> **React reducers MUST be pure functions** — same input, same output, no side effects. This means no module-level mutable variables, no `Date.now()` calls, no random numbers. Move anything mutable into the state itself. React 18 StrictMode exists specifically to catch this class of bug.

---

## 11. The Unlocked Back Door

**Category:** Type Safety | **Severity:** Important

### The Analogy

Your house has a front door with three locks, a deadbolt, and a security camera. But there's a back door that's always open because someone wrote "just use the back door, it's fine" on a sticky note. That's what `as any` does in TypeScript — it bypasses the entire type system.

### The Problem

The sidebar-provider had 14 uses of `as any` when sending messages:

```typescript
// BEFORE: type system bypassed
this.connection?.send({ type: 'save_config', config: configWithoutKey } as any);
this.connection?.send({ type: 'list_models', backend, api_key } as any);
this.connection?.send({ type: 'get_jira_profiles' } as any);
// ^^ If field names are wrong, no compile error. Silent protocol mismatch.
```

The `ExtensionMessage` type was also missing two variants (`fileSelected`, `showSessionHistory`) that were sent via `as any` casts.

### The Fix

We added the missing types and replaced all `as any` with proper types:

```typescript
// AFTER: type system enforced
this.connection?.send({ type: 'save_config', config } as ClientMessage);
this.postToWebview({ type: 'fileSelected', path: uri.fsPath, name });
// ^^ Now TypeScript checks every field name and type at compile time
```

### The Lesson

> **Every `as any` is a bug waiting to happen.** It tells TypeScript "trust me, I know what I'm doing" — but six months from now, neither you nor your teammates will remember what the correct shape was. If the types don't fit, fix the types, don't bypass them.

---

## 12. The Leaky Faucet

**Category:** Memory | **Severity:** Important

### The Analogy

A faucet that drips one drop per second. You don't notice it at first. After a week, there's a puddle. After a month, the floor is damaged. That's what memory leaks look like in long-running applications — imperceptible at first, catastrophic over time.

### The Problems (Multiple)

**Leak 1: DiffContentProvider never cleared between sessions**
```typescript
// BEFORE: diffs accumulated across sessions
// Each approval stores ~2 files worth of content
// If user never approves/rejects, content stays forever
private content = new Map<string, string>(); // Never cleared on new session
```

**Leak 2: setTimeout without cleanup in CodeBlock**
```typescript
// BEFORE: timer fires after component unmounts
setCopied(true);
setTimeout(() => setCopied(false), 2000);
// ^^ If component unmounts in <2 seconds, React warns about state update on unmounted component
```

### The Fixes

```typescript
// Leak 1 fix: clear on new session
if (msg.type === 'session_info') {
    this.diffProvider.clearAll(); // Free all stored diffs
}

// Leak 2 fix: store timer in ref, clean up on unmount
const timerRef = useRef<ReturnType<typeof setTimeout> | null>(null);
useEffect(() => {
    return () => { if (timerRef.current) clearTimeout(timerRef.current); };
}, []);
const handleCopy = useCallback(() => {
    if (timerRef.current) clearTimeout(timerRef.current);
    timerRef.current = setTimeout(() => setCopied(false), 2000);
}, []);
```

### The Lesson

> **Every `Map`, `Set`, cache, and timer is a potential memory leak.** Ask yourself: "When does this get cleaned up?" If the answer is "never" or "I'm not sure," you have a leak. In VS Code webviews, memory is especially precious — the Chromium renderer process has limited memory.

---

## 13. The Broken Telephone

**Category:** Security | **Severity:** Important

### The Analogy

A children's game where a message is whispered around a circle. By the end, "purple elephants" becomes "purple telephones." Now imagine if anyone in the circle could inject their own message. That's what happens when you don't validate `postMessage` data.

### The Problem

The `useVSCode` hook blindly cast incoming messages to `ExtensionMessage`:

```typescript
// BEFORE: trust everything
const listener = (event: MessageEvent) => {
    const message = event.data as ExtensionMessage;  // No validation!
    handlerRef.current(message);
};
```

`window.addEventListener("message")` receives ALL messages posted to the window — including from other VS Code extensions or injected scripts. A malformed message would crash the reducer.

### The Fix

```typescript
// AFTER: validate before dispatch
const listener = (event: MessageEvent) => {
    const message = event.data;
    if (message && typeof message === "object" && "type" in message) {
        handlerRef.current(message as ExtensionMessage);
    }
};
```

### The Lesson

> **Never trust data from `postMessage`.** Always validate the shape before processing. In VS Code webviews this is low-risk (messages come from the extension host), but defense-in-depth prevents entire categories of bugs.

---

## 14. The One-Way Mirror

**Category:** UX Logic | **Severity:** Important

### The Analogy

A security guard who stamps "APPROVED" on a document and THEN asks you to read it. You can't un-approve it even if you find something wrong. That's what the SubagentApprovalWidget did — it sent the approval message to the server *before* opening the diff viewer.

### The Problem

```typescript
// BEFORE: approve first, review second
const handleAccept = () => {
    postMessage({ type: "approvalResult", callId, approved: true }); // Approved!
    // THEN open diff viewer... too late to reject
    if (isFileTool) {
        postMessage({ type: "showDiff", callId, toolName, arguments: data.arguments });
    }
    onDismiss();
};
```

### The Fix

We separated the actions: a "View Diff" button lets the user review before clicking Accept:

```typescript
// AFTER: review first, then decide
const handleShowDiff = () => {
    postMessage({ type: "showDiff", callId, toolName, arguments });
};
const handleAccept = () => {
    postMessage({ type: "approvalResult", callId, approved: true });
    onDismiss();
};
// UI now has: [Accept] [View Diff] [Reject]
```

### The Lesson

> **Destructive actions should always come AFTER the user has reviewed the consequences.** This is a core UX principle. Preview before commit. Review before approve. Show the diff before accepting the change.

---

## 15. The Confused Liar

**Category:** State Bug | **Severity:** Important

### The Analogy

You ask a waiter to cancel your order. They nod, but the kitchen display shows "Order Confirmed." Why? Because the display checks "is there an order?" (always yes — the data structure exists) instead of "was it cancelled?" (a separate flag that was never tracked).

### The Problem

ClarifyWidget used a `dismissed` boolean and checked `responses` truthiness for the label:

```typescript
// BEFORE: always shows "submitted" — even after cancel!
const [dismissed, setDismissed] = useState(false);
const [responses, setResponses] = useState<Record<...>>(() => {
    const init = {};
    for (const q of questions) init[qId] = ""; // Always truthy object
    return init;
});

// After cancel:
setDismissed(true);
// responses is still the init object (truthy)

// Display:
{dismissed && `[Clarification ${responses ? "submitted" : "cancelled"}]`}
//                                ^^^^^^^^^ Always truthy! Always "submitted"!
```

### The Fix

Track the outcome explicitly:

```typescript
// AFTER: separate state for the outcome
const [dismissedAs, setDismissedAs] = useState<"submitted" | "cancelled" | null>(null);

// In handleCancel:
setDismissedAs("cancelled");  // Explicitly tracks the action

// Display:
{dismissedAs && `[Clarification ${dismissedAs}]`}
```

### The Lesson

> **Don't derive UI labels from data that wasn't designed for that purpose.** `responses` was designed to hold form data, not to indicate whether the form was submitted or cancelled. When you need to display an outcome, track the outcome directly.

---

## 16. The Sluggish Painter

**Category:** Performance | **Severity:** Important

### The Analogy

An artist who repaints every painting in the gallery every time a visitor walks in — even if nothing changed. Most paintings are identical to before, but the artist insists on starting from scratch each time. That's React without `React.memo`.

### The Problem

Zero components were wrapped in `React.memo`. During streaming, every token (50+ per second) triggered `TEXT_DELTA` → `App` re-renders → ALL children re-render — including `StatusBar`, `BottomBar`, `InputBox`, and every `ToolCard` in the timeline. With 100+ tool cards, this caused visible jank.

### The Fix

We wrapped 9 stable components in `React.memo`:

```typescript
// BEFORE
export function StatusBar({ ... }: StatusBarProps) { ... }
export function BottomBar({ ... }: BottomBarProps) { ... }
export function ToolCard({ ... }: ToolCardProps) { ... }

// AFTER — only re-renders when props actually change
export const StatusBar = memo(function StatusBar({ ... }: StatusBarProps) { ... });
export const BottomBar = memo(function BottomBar({ ... }: BottomBarProps) { ... });
export const ToolCard = memo(function ToolCard({ ... }: ToolCardProps) { ... });
```

### The Lesson

> **In streaming/real-time UIs, `React.memo` is not optional.** Without it, every state update re-renders the entire component tree. Wrap components that receive stable props (callbacks, completed data) in `memo` to prevent unnecessary work. Profile with React DevTools if you're unsure which components to wrap.

---

## 17. The Nested Loop Tax

**Category:** Performance | **Severity:** Minor

### The Analogy

Finding a book in a library by walking through every shelf for every patron who walks in. If 10 patrons each need 10 books, you walk 100 shelves instead of building an index once and looking up 10 times. That's O(n*m) vs O(n+m).

### The Problem

For each `subagent` timeline entry, `ChatHistory` scanned the entire timeline to check if a matching tool entry existed:

```typescript
// BEFORE: O(n*m) — n timeline entries * m subagents
const hasDelegationToolEntry = timeline.some(
    (e) => e.type === "tool" && e.callId === saInfo.parentToolCallId,
);
```

### The Fix

Pre-compute a Set of tool callIds in O(n), then lookup in O(1):

```typescript
// AFTER: O(n+m)
const toolCallIds = useMemo(() => {
    const ids = new Set<string>();
    for (const entry of timeline) {
        if (entry.type === "tool") ids.add(entry.callId);
    }
    return ids;
}, [timeline]);

// Later: O(1) lookup
if (toolCallIds.has(saInfo.parentToolCallId)) return null;
```

### The Lesson

> **When you see `.find()` or `.some()` inside a `.map()` or `.filter()`, you likely have an O(n*m) problem.** The fix is almost always a Set or Map pre-computed outside the loop.

---

## 18. The Passwordless Wifi

**Category:** Security | **Severity:** Important

### The Analogy

Your home wifi password is taped to the router in the living room. Anyone who visits can see it. That's what happened when the API key was sent through the postMessage bridge in plaintext.

### The Problem

When fetching model lists, the raw API key was sent from the webview through postMessage:

```typescript
// BEFORE: API key travels through 3 process memory spaces
postMessage({ type: "listModels", backend, base_url: baseUrl, api_key: apiKey });
```

### The Fix

Send a sentinel value that tells the extension host to use the key already stored in SecretStorage:

```typescript
// AFTER: key never leaves SecretStorage
postMessage({ type: "listModels", backend, base_url: baseUrl, api_key: "__use_stored__" });

// Extension host resolves the sentinel:
if (resolvedKey === '__use_stored__' && this.secrets) {
    resolvedKey = await this.secrets.get('claraity.apiKey') ?? '';
}
```

### The Lesson

> **Secrets should stay in secure storage as long as possible.** Don't ferry API keys through IPC bridges, event emitters, or log-visible channels when you can resolve them at the point of use. VS Code's `SecretStorage` exists for exactly this purpose.

---

## 19. The Unlabeled Buttons

**Category:** Accessibility | **Severity:** Minor

### The Analogy

A building with no signs on any door. Sighted people can peek through windows, but blind people have no idea which room is which. That's a UI without ARIA attributes — screen reader users can't navigate it.

### The Problem

Zero ARIA attributes across 18 components. Icon-only buttons had no accessible names. The mention dropdown had no `role="listbox"`. The mode toggle had no `role="radiogroup"`. The streaming area had no `aria-live` region.

### The Fix

We added ARIA attributes throughout:

```tsx
// Toolbar
<div role="toolbar" aria-label="ClarAIty toolbar">
  <button aria-label="New Chat"><i className="codicon codicon-add" /></button>

// Mode toggle
<div role="radiogroup" aria-label="Agent mode">
  <button role="radio" aria-checked={mode === "plan"}>Plan</button>

// Mention dropdown
<div role="listbox" id="mention-listbox" aria-label="File suggestions">
  <div role="option" aria-selected={i === mentionIndex} id={`mention-${i}`}>

// Streaming content
<div aria-live="polite">
```

### The Lesson

> **Accessibility is not optional polish — it's a requirement for marketplace extensions.** VS Code users include people with screen readers, keyboard-only navigation, and high-contrast themes. Add `role`, `aria-label`, `aria-live`, and keyboard handlers from the start — retrofitting is much harder.

---

## 20. The Permanent Sticky Note

**Category:** Memory | **Severity:** Important

### The Analogy

Every time you request a document for review, a copy is made and stuck to the wall. Even after you approve or reject it, old copies from last month are still there. After a year, the wall is buried. That's what `DiffContentProvider` did — stored file content for diffs but never cleaned up between sessions.

### The Fix

```typescript
// Clear all stored diffs when a new session starts
if (msg.type === 'session_info') {
    this.diffProvider.clearAll();
}
```

### The Lesson

> **Every cache needs a clear/evict strategy aligned to the application lifecycle.** When a new session starts, old session data should be freed.

---

## 21-35. Quick Lessons

### 21. The Time Bomb Timer
`setTimeout` in a React component without cleanup in `useEffect` → state update on unmounted component. **Always store timer refs and clear on unmount.**

### 22. The Invisible Error
If the webview JS file doesn't exist, `<script src="missing.js">` silently fails and the panel is blank. **Always check if critical assets exist and show a fallback.**

### 23. The Narrow Funnel
DOMPurify's default config allows `<img>`, `<iframe>`, `<form>`. In a chat UI, you only need prose + code tags. **Restrict your sanitizer allowlist to exactly what you render.**

### 24. The Sticky Settings Panel
Auto-closing the settings panel 3 seconds after save is disorienting — the user wants to verify their changes. **Let users control when panels close.**

### 25. The Copy-Paste Bomb
No input length limit means pasting 10MB of text freezes the webview. **Cap input at a reasonable size (100KB) and truncate silently.**

### 26. The Nuclear Undo
`checkpoints.splice(idx)` removed the target checkpoint AND everything after it. Undoing turn 5 destroyed turns 6-10. **Use `splice(idx, 1)` to remove only the specific item.**

### 27. The Goldfish Memory
`MAX_HISTORY = 10` meant only 10 turns of undo history. For long sessions, users lost the ability to undo early work. **50 is a better default — or make it configurable.**

### 28. The Invisible Badge
`charts.green` ThemeColor has poor contrast on many VS Code themes. **Use semantic colors like `gitDecoration.addedResourceForeground` that adapt to the theme.**

### 29. The Key Collision
`Ctrl+Shift+H` is "Replace in Files" in many keymaps. **Check VS Code's default keybindings before claiming a shortcut. Use less common combos.**

### 30. The Orphaned Child
`deactivate()` returned immediately while a 3-second force-kill timer was pending. VS Code could tear down the extension host before the timer fired, leaving an orphaned Python process. **Make `deactivate()` async and wait for cleanup.**

### 31. The Growing Logbook
A `Set<string>` tracking shown terminal commands grew without limit. **Cap at a reasonable size (1000) and clear when full.**

### 32. The Minified Mystery
`sourcemap: !production` meant production builds had no sourcemaps. When users reported crashes, stack traces pointed to minified code. **Always ship sourcemaps — the 130KB cost saves hours of debugging.**

### 33. The Future-Proof Trap
`target: "esnext"` in Vite emits the latest JavaScript syntax, but VS Code 1.85 ships Chromium ~120 which may not support all of it. **Use `"es2022"` or `"chrome120"` for safe compatibility.**

### 34. The Injection Needle
Interpolating a package name into a Python `-c` script string: `f"...version('{pkg}')..."`. If the value ever contains quotes, it's code injection. **Use subprocess arguments (`sys.argv`) and JSON for safe value passing.**

### 35. The Ghost Setting
Code read `claraity.webviewMode` from configuration, but the setting was never declared in `package.json`'s `contributes.configuration`. Users couldn't discover or configure it. After the inline HTML fallback was removed, the setting was dead code. **Remove unused code paths. Don't leave ghost references.**

---

## Cheat Sheet: Questions to Ask Before Shipping

| Category | Question |
|----------|----------|
| **Error handling** | What happens when the external process dies? |
| **Memory** | Does this collection have a size limit? |
| **State** | Is the UI state consistent with the system state? |
| **Types** | Am I bypassing TypeScript with `as any`? |
| **Platform** | Does this work on Linux/Mac, or only Windows? |
| **Security** | Is this secret staying in secure storage? |
| **UX** | Can the user recover without reloading? |
| **Build** | Does `vsce package` produce a complete, working extension? |
| **React** | Is this reducer pure? Are expensive components memoized? |
| **Accessibility** | Can a screen reader user navigate this? |

---

*Generated from the ClarAIty VS Code extension code review — March 2026*
*35 bugs found, 35 bugs fixed, 314 tests passing, 0 regressions*
