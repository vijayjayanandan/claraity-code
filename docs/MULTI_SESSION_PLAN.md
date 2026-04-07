# Multi-Session Support for ClarAIty VS Code Extension

**Status:** Planned
**Estimated scope:** ~500-700 lines TypeScript, ~50 lines Python
**Reference:** Claude Code VS Code extension (uses editor tabs for parallel sessions)

---

## 1. Goal

Allow users to have multiple chat sessions open simultaneously in VS Code:
- **Sidebar** hosts one session (the "home" session)
- **Editor tabs** host additional sessions (via `WebviewPanel`)
- Both render the same React app
- Sessions share a single Python agent process (one streams at a time)
- User can reference one conversation while working in another

---

## 2. Current Architecture

```
extension.ts
  └─ connection (1 StdioConnection)
  └─ sidebarProvider (1 ClarAItySidebarProvider)
       └─ view (1 WebviewView)
            └─ handleWebviewMessage() — 60+ cases, ~460 lines
            └─ handleServerMessage()  — routes server events to webview

stdio_server.py
  └─ StdioProtocol
       └─ _session_id (1 active session)
       └─ _store (1 MessageStore)
       └─ _send_json() — pushes events over TCP
```

**Problem:** One sidebar webview, one active session. No way to view two sessions simultaneously.

---

## 3. Target Architecture

```
extension.ts
  └─ connection (1 StdioConnection)
  └─ webviewRouter (routes server events by session_id)
  └─ sidebarProvider (uses shared WebviewHost)
  │    └─ WebviewHost (sessionId: "abc")
  └─ panelManager (tracks editor tab panels)
       └─ WebviewPanel #1 → WebviewHost (sessionId: "def")
       └─ WebviewPanel #2 → WebviewHost (sessionId: "ghi")
```

All webviews register with the router. Server events are delivered to the correct webview based on session ID.

---

## 4. Implementation Phases

### Phase 1: Extract Shared WebviewHost (refactor only, no behavior change)

**Goal:** Move webview setup and message handling out of `sidebar-provider.ts` into a reusable module that both sidebar and editor tabs can use.

**New file: `claraity-vscode/src/webview-host.ts`**

```typescript
export class WebviewHost {
    private webview: vscode.Webview;
    private sessionId: string | null = null;
    private connection: AnyConnection | null;
    private disposables: vscode.Disposable[] = [];

    constructor(
        webview: vscode.Webview,
        extensionUri: vscode.Uri,
        connection: AnyConnection | null,
        log: OutputChannel,
    ) { ... }

    /** Generate webview HTML — extracted from resolveWebviewView() */
    static getHtmlContent(webview: vscode.Webview, extensionUri: vscode.Uri): string { ... }

    /** Handle message from webview React app */
    handleWebviewMessage(msg: WebviewMessage): void { ... }

    /** Handle message from server, forward to webview */
    handleServerMessage(msg: ServerMessage): void { ... }

    /** Send message to webview */
    postToWebview(msg: ExtensionMessage): void { ... }

    setConnection(conn: AnyConnection): void { ... }
    getSessionId(): string | null { return this.sessionId; }
    dispose(): void { ... }
}
```

**Changes to `sidebar-provider.ts`:**
- Remove `handleWebviewMessage()` body (~460 lines) — delegate to `WebviewHost`
- Remove `handleServerMessage()` body — delegate to `WebviewHost`
- Remove HTML generation — delegate to `WebviewHost.getHtmlContent()`
- Keep `resolveWebviewView()` as thin wrapper that creates a `WebviewHost`
- Keep `DiffContentProvider` (sidebar-specific, can be shared later)

**What moves:**
| From sidebar-provider.ts | To webview-host.ts |
|---|---|
| `handleWebviewMessage()` cases (line 314-777) | `WebviewHost.handleWebviewMessage()` |
| `handleServerMessage()` routing (line 242-309) | `WebviewHost.handleServerMessage()` |
| `getHtmlForWebview()` (HTML generation) | `WebviewHost.getHtmlContent()` |
| `sendChatWithAttachments()` (line 979-1040) | `WebviewHost.sendChatWithAttachments()` |
| `postToWebview()` (line 1069-1071) | `WebviewHost.postToWebview()` |

**What stays in sidebar-provider.ts:**
| Method | Why |
|---|---|
| `resolveWebviewView()` | VS Code API contract for sidebar |
| `setConnection()` | Delegates to WebviewHost |
| `DiffContentProvider` | Used across all webviews (registered once) |
| `openDiffEditor()` | Can be shared, but keep in provider for now |

**Verification:** Extension behaves identically after refactor. All existing functionality preserved.

---

### Phase 2: Create Panel Manager

**Goal:** Manage `WebviewPanel` instances (editor tabs) for additional sessions.

**New file: `claraity-vscode/src/panel-manager.ts`**

```typescript
export class ChatPanelManager {
    private panels: Map<string, { panel: vscode.WebviewPanel; host: WebviewHost }> = new Map();
    private connection: AnyConnection | null = null;

    constructor(
        private extensionUri: vscode.Uri,
        private log: vscode.OutputChannel,
    ) {}

    /**
     * Create a new editor tab with a fresh session.
     * Returns the session ID assigned to the tab.
     */
    createPanel(sessionId?: string): string {
        const panel = vscode.window.createWebviewPanel(
            'claraity.chatPanel',        // viewType (for serializer)
            'ClarAIty: New Chat',        // tab title
            vscode.ViewColumn.One,
            {
                enableScripts: true,
                retainContextWhenHidden: true,   // keep state when tab not visible
                localResourceRoots: [this.extensionUri],
            },
        );

        const host = new WebviewHost(panel.webview, this.extensionUri, this.connection, this.log);
        const id = sessionId ?? crypto.randomUUID();
        this.panels.set(id, { panel, host });

        // Disposal cleanup
        panel.onDidDispose(() => {
            this.panels.delete(id);
        });

        // If no sessionId provided, tell server to create a new session
        // and route the session_info response to this panel
        if (!sessionId) {
            this.connection?.send({ type: 'new_session', target_panel: id });
        }

        return id;
    }

    /** Get all active WebviewHosts (for routing) */
    getHosts(): Map<string, WebviewHost> {
        const result = new Map<string, WebviewHost>();
        for (const [id, entry] of this.panels) {
            result.set(id, entry.host);
        }
        return result;
    }

    /** Update tab title when first message arrives */
    updatePanelTitle(sessionId: string, title: string): void {
        const entry = this.panels.get(sessionId);
        if (entry) {
            entry.panel.title = `ClarAIty: ${title.slice(0, 40)}`;
        }
    }

    setConnection(conn: AnyConnection): void {
        this.connection = conn;
        for (const entry of this.panels.values()) {
            entry.host.setConnection(conn);
        }
    }

    dispose(): void {
        for (const entry of this.panels.values()) {
            entry.panel.dispose();
        }
        this.panels.clear();
    }
}
```

**`WebviewPanelSerializer` (tab restoration on VS Code reload):**

```typescript
export class ChatPanelSerializer implements vscode.WebviewPanelSerializer {
    constructor(private manager: ChatPanelManager) {}

    async deserializeWebviewPanel(
        panel: vscode.WebviewPanel,
        state: { sessionId: string },
    ): Promise<void> {
        // Restore panel from serialized state
        // The React app inside will request session replay on mount
        this.manager.restorePanel(panel, state.sessionId);
    }
}
```

**Register in `extension.ts`:**
```typescript
// In activate():
const panelManager = new ChatPanelManager(context.extensionUri, log);
context.subscriptions.push(panelManager);

vscode.window.registerWebviewPanelSerializer(
    'claraity.chatPanel',
    new ChatPanelSerializer(panelManager),
);
```

---

### Phase 3: Message Router

**Goal:** Route server events to the correct webview (sidebar or editor tab) based on session ID.

**New file: `claraity-vscode/src/message-router.ts`**

```typescript
export class MessageRouter {
    private sidebarHost: WebviewHost | null = null;
    private panelManager: ChatPanelManager;
    private activeSessionId: string | null = null;

    constructor(panelManager: ChatPanelManager) {
        this.panelManager = panelManager;
    }

    setSidebarHost(host: WebviewHost): void {
        this.sidebarHost = host;
    }

    /**
     * Route a server message to the correct webview.
     *
     * Routing logic:
     * 1. Messages with explicit session_id → find matching webview
     * 2. Stream events (text_delta, tool calls, etc.) → active session's webview
     * 3. Broadcast events (sessions_list) → all webviews
     */
    route(msg: ServerMessage): void {
        // Session-specific events (always have session_id)
        if (msg.type === 'session_info') {
            this.activeSessionId = msg.session_id;
            const target = this.findHost(msg.session_id);
            target?.handleServerMessage(msg);
            return;
        }

        // Broadcast events — send to all webviews
        if (msg.type === 'sessions_list') {
            this.broadcast(msg);
            return;
        }

        // Session history replay — goes to session that requested it
        if (msg.type === 'session_history') {
            const target = this.findHost(msg.session_id);
            target?.handleServerMessage(msg);
            return;
        }

        // Stream events — route to active session
        const target = this.findHost(this.activeSessionId);
        target?.handleServerMessage(msg);
    }

    /** Find the WebviewHost for a given session ID */
    private findHost(sessionId: string | null): WebviewHost | null {
        if (!sessionId) return this.sidebarHost;

        // Check sidebar first
        if (this.sidebarHost?.getSessionId() === sessionId) {
            return this.sidebarHost;
        }

        // Check editor tab panels
        const panelHosts = this.panelManager.getHosts();
        return panelHosts.get(sessionId) ?? null;
    }

    /** Send to all webviews */
    private broadcast(msg: ServerMessage): void {
        this.sidebarHost?.handleServerMessage(msg);
        for (const host of this.panelManager.getHosts().values()) {
            host.handleServerMessage(msg);
        }
    }
}
```

**Modify `extension.ts` `wireConnection()`:**

Current (line 88-186):
```typescript
function wireConnection(conn, statusBar) {
    conn.onMessage((msg) => {
        sidebarProvider.handleServerMessage(msg);  // single target
        // ... extension-level handling
    });
}
```

After:
```typescript
function wireConnection(conn, statusBar) {
    conn.onMessage((msg) => {
        router.route(msg);  // multi-target routing
        // ... extension-level handling (unchanged)
    });
}
```

---

### Phase 4: Commands & UX

**Goal:** Wire up commands for creating tabs and integrate with session history.

**Modify `claraity.newChat` command (extension.ts line 190-199):**

```typescript
// Current: always resets sidebar
registerCommand('claraity.newChat', () => {
    connection?.send({ type: 'new_session' });
});

// After: sidebar "+" resets sidebar, palette/keybinding opens tab
registerCommand('claraity.newChat', () => {
    connection?.send({ type: 'new_session' });
});

registerCommand('claraity.newTab', () => {
    panelManager.createPanel();
});
```

**Add to `package.json` commands:**
```json
{
    "command": "claraity.newTab",
    "title": "ClarAIty: New Chat in Tab",
    "icon": "$(split-horizontal)"
}
```

**Add to sidebar header menu (package.json view/title):**
```json
{
    "command": "claraity.newTab",
    "when": "view == claraity.chatView",
    "group": "navigation@6"
}
```

**Session history "Open in tab" option:**

In `SessionPanel.tsx`, add a button/context menu:
```tsx
<button onClick={() => vscode.postMessage({
    type: 'resumeSessionInTab',
    sessionId: session.id,
})}>
    Open in Tab
</button>
```

Handle in `webview-host.ts`:
```typescript
case 'resumeSessionInTab':
    // Bubble up to extension to create a panel
    this.onRequestNewTab?.(msg.sessionId);
    break;
```

---

### Phase 5: Server-Side Session Tagging (Optional Enhancement)

**Goal:** Add `session_id` to all server events for robust routing.

**Modify `stdio_server.py` `_send_json()` (line 387-403):**

```python
async def _send_json(self, data: dict) -> None:
    # Tag every outgoing event with the active session ID
    if self._session_id and 'session_id' not in data:
        data['session_id'] = self._session_id

    msg = wrap_notification(data)
    # ... rest unchanged
```

This is a small, safe change. The extension can use this field for routing instead of tracking `activeSessionId` client-side.

**Note:** This phase is optional for Phase 1. Client-side tracking of `activeSessionId` (set when `session_info` arrives) is sufficient for the initial implementation since only one session streams at a time.

---

### Phase 6: Tab State Persistence

**Goal:** Restore editor tabs after VS Code reload.

The `WebviewPanelSerializer` (Phase 2) handles restoring the panel. The React app inside needs to request session replay on mount.

**In the React app (`App.tsx`), on mount:**
```typescript
useEffect(() => {
    // If we have a persisted sessionId from VS Code state, request replay
    const savedState = vscode.getState();
    if (savedState?.sessionId) {
        vscode.postMessage({ type: 'resumeSession', sessionId: savedState.sessionId });
    }
}, []);
```

**Persist session ID via `vscode.setState()`:**

In the reducer, when `SET_SESSION_INFO` fires:
```typescript
case 'SET_SESSION_INFO': {
    // ... existing logic
    vscode.setState({ sessionId: action.sessionId });
    // ...
}
```

---

## 5. File Change Summary

| File | Change Type | Scope |
|------|-------------|-------|
| **claraity-vscode/src/webview-host.ts** | New | ~300 lines — extracted from sidebar-provider |
| **claraity-vscode/src/panel-manager.ts** | New | ~120 lines — WebviewPanel lifecycle |
| **claraity-vscode/src/message-router.ts** | New | ~80 lines — event routing |
| **claraity-vscode/src/sidebar-provider.ts** | Refactor | ~-400 lines (moved to webview-host), +30 lines (delegation) |
| **claraity-vscode/src/extension.ts** | Modify | ~+50 lines (panel manager, router, commands) |
| **claraity-vscode/package.json** | Modify | ~+15 lines (new command, serializer registration) |
| **claraity-vscode/webview-ui/src/components/SessionPanel.tsx** | Modify | ~+20 lines ("Open in tab" button) |
| **claraity-vscode/webview-ui/src/App.tsx** | Modify | ~+10 lines (vscode.setState for persistence) |
| **src/server/stdio_server.py** | Modify | ~+5 lines (session_id tagging in _send_json) |

**Net new code:** ~500 lines TypeScript, ~5 lines Python
**Net removed code:** ~400 lines moved from sidebar-provider to webview-host (not deleted, relocated)

---

## 6. Edge Cases & Mitigations

| Scenario | Behavior | Implementation |
|----------|----------|----------------|
| **Tab closed while streaming** | Cancel stream for that session, no effect on other tabs | Panel dispose handler sends interrupt if session is active |
| **Two tabs send messages simultaneously** | Second message queues; server processes one at a time | Server's existing stdin queue handles this. Extension can show "waiting" indicator in queued tab |
| **VS Code reload** | Tabs restored via serializer, sessions replayed from JSONL | `WebviewPanelSerializer` + `vscode.getState()` |
| **Connection lost** | All webviews show "Disconnected" state | Router broadcasts `connectionStatus` to all webviews |
| **Connection restored** | Active session resumes, other tabs show cached state | Reconnect handler sends session_info, router delivers to active tab |
| **Session deleted while open in tab** | Close the tab, notify user | Handle `session_deleted` event, dispose matching panel |
| **Same session opened in sidebar AND tab** | Prevent: router checks for duplicates | `createPanel()` checks if session already open, focuses existing |

---

## 7. UX Flow

### New Tab from Sidebar Header
```
User clicks split/tab icon in sidebar header
  → extension.ts: claraity.newTab command fires
  → panelManager.createPanel()
  → New WebviewPanel opens in editor area
  → WebviewHost sends { type: 'new_session' } to server
  → Server creates session, responds with session_info
  → Router delivers to new panel's webview
  → User sees fresh "Ready to code?" screen in editor tab
```

### Open Session from History in Tab
```
User opens session history → clicks "Open in Tab" on a session
  → webview posts { type: 'resumeSessionInTab', sessionId }
  → WebviewHost bubbles to extension
  → panelManager.createPanel(sessionId)
  → New WebviewPanel opens, sends resume_session to server
  → Server replays session from JSONL
  → Router delivers session_history to new panel
  → User sees full conversation history in editor tab
```

### Switch Active Session
```
User clicks on a different tab (or clicks sidebar)
  → VS Code focuses that webview
  → User types a message
  → WebviewHost sends chat_message to server
  → Server switches active session (existing _switch_session logic)
  → Streaming begins, events route to this webview
```

---

## 8. What This Does NOT Include (Future Work)

- **True parallel streaming** — multiple agent processes streaming simultaneously. Current plan serializes: one session streams, others display cached state.
- **Drag session from sidebar to tab** — would require session transfer protocol.
- **Tab groups/split view** — relies on VS Code's native tab management.
- **Cross-window session sharing** — each VS Code window has its own agent process.

---

## 9. Implementation Order

| Order | Phase | Risk | Depends On |
|-------|-------|------|------------|
| 1 | Extract WebviewHost from sidebar-provider | Low (pure refactor) | Nothing |
| 2 | Create PanelManager | Low | Phase 1 |
| 3 | Create MessageRouter | Medium (routing correctness) | Phase 1 |
| 4 | Wire commands & UX | Low | Phase 2, 3 |
| 5 | Server session tagging | Low (optional) | Nothing |
| 6 | Tab persistence | Medium (serializer edge cases) | Phase 2, 4 |

**Recommended approach:** Complete Phase 1 first and verify no regressions. Then Phase 2+3 together (they're complementary). Phase 4 makes it user-facing. Phase 5-6 are polish.

---

## 10. Testing Checklist

- [ ] Sidebar still works identically after Phase 1 refactor
- [ ] "New Tab" command opens editor tab with fresh session
- [ ] Typing in editor tab sends messages and receives responses
- [ ] Sidebar and editor tab sessions are independent
- [ ] Switching between tabs switches active session on server
- [ ] Session history "Open in Tab" works
- [ ] Closing a tab while streaming cancels cleanly
- [ ] VS Code reload restores editor tabs
- [ ] Connection loss shows disconnected in all webviews
- [ ] Same session can't open in two places simultaneously
- [ ] Tab title updates with first message preview
