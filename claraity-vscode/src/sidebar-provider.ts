/**
 * WebView sidebar provider for the ClarAIty chat panel.
 *
 * Responsibilities:
 * - Provide WebView HTML that loads the React app
 * - Bridge messages between WebSocket server and WebView
 * - Trigger VS Code native actions (diff editor, file open)
 */

import * as vscode from 'vscode';
import { AgentConnection } from './agent-connection';
import { ServerMessage, WebViewMessage } from './types';


/**
 * Content provider for the claraity-diff: URI scheme.
 *
 * Stores virtual document content (original/modified) for VS Code's
 * built-in diff editor. Content is keyed by "{callId}/{side}" where
 * side is "original" or "modified".
 */
export class DiffContentProvider implements vscode.TextDocumentContentProvider {
    private content = new Map<string, string>();
    private _onDidChange = new vscode.EventEmitter<vscode.Uri>();
    readonly onDidChangeTextDocument = this._onDidChange.event;

    setContent(callId: string, side: 'original' | 'modified', text: string): void {
        this.content.set(`${callId}/${side}`, text);
    }

    provideTextDocumentContent(uri: vscode.Uri): string {
        // URI format: claraity-diff:/{callId}/{side}?label=...
        const key = uri.path.startsWith('/') ? uri.path.slice(1) : uri.path;
        return this.content.get(key) ?? '';
    }

    clear(callId: string): void {
        this.content.delete(`${callId}/original`);
        this.content.delete(`${callId}/modified`);
    }

    dispose(): void {
        this._onDidChange.dispose();
    }
}


export class ClarAItySidebarProvider implements vscode.WebviewViewProvider {
    private view?: vscode.WebviewView;
    private diffProvider: DiffContentProvider;
    private diffProviderRegistration: vscode.Disposable;

    constructor(
        private extensionUri: vscode.Uri,
        private connection: AgentConnection,
    ) {
        // Register diff content provider for claraity-diff: URI scheme
        this.diffProvider = new DiffContentProvider();
        this.diffProviderRegistration = vscode.workspace.registerTextDocumentContentProvider(
            'claraity-diff',
            this.diffProvider,
        );
        // Forward server messages to webview
        this.connection.onMessage((msg) => {
            this.handleServerMessage(msg);
        });

        // Forward connection status to webview
        this.connection.onConnected(() => {
            this.postToWebview({ type: 'connectionStatus', status: 'connected' });
        });

        this.connection.onDisconnected(() => {
            this.postToWebview({ type: 'connectionStatus', status: 'disconnected' });
        });
    }

    resolveWebviewView(
        webviewView: vscode.WebviewView,
        _context: vscode.WebviewViewResolveContext,
        _token: vscode.CancellationToken,
    ): void {
        this.view = webviewView;

        webviewView.webview.options = {
            enableScripts: true,
            localResourceRoots: [this.extensionUri],
        };

        webviewView.webview.html = this.getHtmlForWebview(webviewView.webview);

        // Handle messages from webview
        webviewView.webview.onDidReceiveMessage((message: WebViewMessage) => {
            this.handleWebviewMessage(message);
        });
    }

    /**
     * Server -> Extension -> WebView message routing.
     */
    private handleServerMessage(msg: ServerMessage): void {
        // Forward to webview for rendering
        this.postToWebview({ type: 'serverMessage', payload: msg });

        // Extract session info for status bar etc.
        if (msg.type === 'session_info') {
            this.postToWebview({
                type: 'sessionInfo',
                sessionId: msg.session_id,
                model: msg.model_name,
                permissionMode: msg.permission_mode,
                autoApproveCategories: msg.auto_approve_categories,
            });
        }

        // Stop reconnecting on non-recoverable errors
        if (msg.type === 'error' && msg.recoverable === false) {
            this.connection.disconnect();
        }
    }

    /**
     * WebView -> Extension -> Server message routing.
     */
    private handleWebviewMessage(msg: WebViewMessage): void {
        switch (msg.type) {
            case 'chatMessage':
                this.connection.send({
                    type: 'chat_message',
                    content: msg.content,
                });
                break;

            case 'approvalResult':
                this.connection.send({
                    type: 'approval_result',
                    call_id: msg.callId,
                    approved: msg.approved,
                    auto_approve_future: msg.autoApproveFuture ?? false,
                    feedback: msg.feedback ?? null,
                });
                break;

            case 'interrupt':
                this.connection.send({ type: 'interrupt' });
                break;

            case 'ready':
                // WebView finished loading — send current connection state
                if (this.connection.isConnected) {
                    this.postToWebview({ type: 'connectionStatus', status: 'connected' });
                }
                break;

            case 'copyToClipboard':
                vscode.env.clipboard.writeText(msg.text);
                break;

            case 'pauseResult':
                this.connection.send({
                    type: 'pause_result',
                    continue_work: msg.continueWork,
                    feedback: msg.feedback ?? null,
                });
                break;

            case 'showDiff':
                this.openDiffEditor(msg.callId, msg.toolName, msg.arguments);
                break;

            case 'clarifyResult':
                this.connection.send({
                    type: 'clarify_result',
                    call_id: msg.callId,
                    submitted: msg.submitted,
                    responses: msg.responses,
                    chat_instead: false,
                    chat_message: null,
                });
                break;

            case 'planApprovalResult':
                this.connection.send({
                    type: 'plan_approval_result',
                    plan_hash: msg.planHash,
                    approved: msg.approved,
                    auto_accept_edits: msg.autoAcceptEdits ?? false,
                    feedback: msg.feedback ?? null,
                });
                break;

            case 'setMode':
                this.connection.send({ type: 'set_mode', mode: msg.mode });
                break;

            case 'getConfig':
                this.connection.send({ type: 'get_config' });
                break;

            case 'saveConfig':
                this.connection.send({ type: 'save_config', config: msg.config } as any);
                break;

            case 'listModels':
                this.connection.send({
                    type: 'list_models',
                    backend: msg.backend,
                    base_url: msg.base_url,
                    api_key: msg.api_key,
                } as any);
                break;

            case 'setAutoApprove':
                this.connection.send({ type: 'set_auto_approve', categories: msg.categories } as any);
                break;

            case 'getAutoApprove':
                this.connection.send({ type: 'get_auto_approve' } as any);
                break;

            case 'newSession':
                this.connection.send({ type: 'new_session' });
                break;
        }
    }

    /**
     * Open VS Code's built-in diff editor for a tool call.
     *
     * For write_file: shows current file (or empty) vs. new content.
     * For edit_file: shows current file vs. file with old_text replaced by new_text.
     */
    private async openDiffEditor(
        callId: string,
        toolName: string,
        args: Record<string, any>,
    ): Promise<void> {
        try {
            let originalContent = '';
            let modifiedContent = '';
            let filePath = '';

            if (toolName === 'write_file') {
                filePath = args.file_path || args.path || '';
                modifiedContent = args.content || '';
                // Try to read existing file
                if (filePath) {
                    try {
                        const uri = vscode.Uri.file(filePath);
                        const bytes = await vscode.workspace.fs.readFile(uri);
                        originalContent = Buffer.from(bytes).toString('utf-8');
                    } catch {
                        // File doesn't exist yet — original is empty
                        originalContent = '';
                    }
                }
            } else if (toolName === 'edit_file') {
                filePath = args.file_path || args.path || '';
                const oldText = args.old_text || '';
                const newText = args.new_text || '';
                if (filePath) {
                    try {
                        const uri = vscode.Uri.file(filePath);
                        const bytes = await vscode.workspace.fs.readFile(uri);
                        originalContent = Buffer.from(bytes).toString('utf-8');
                    } catch {
                        originalContent = '';
                    }
                }
                // Compute modified by applying the replacement.
                // Normalize line endings for comparison (Windows \r\n vs LLM \n)
                // but preserve original line endings in the output.
                const normalizedOriginal = originalContent.replace(/\r\n/g, '\n');
                const normalizedOldText = oldText.replace(/\r\n/g, '\n');
                if (normalizedOriginal.includes(normalizedOldText) && normalizedOldText.length > 0) {
                    // Find the position in normalized content, then apply replacement
                    // preserving the original line endings
                    const idx = normalizedOriginal.indexOf(normalizedOldText);
                    // Map normalized index back to original content:
                    // Count how many \r\n pairs exist before the match position
                    let origIdx = 0;
                    let normIdx = 0;
                    while (normIdx < idx) {
                        if (originalContent[origIdx] === '\r' && originalContent[origIdx + 1] === '\n') {
                            origIdx += 2;
                            normIdx += 1; // \r\n -> \n in normalized
                        } else {
                            origIdx += 1;
                            normIdx += 1;
                        }
                    }
                    // Find the end position similarly
                    let origEnd = origIdx;
                    let normEnd = normIdx;
                    while (normEnd < idx + normalizedOldText.length) {
                        if (originalContent[origEnd] === '\r' && originalContent[origEnd + 1] === '\n') {
                            origEnd += 2;
                            normEnd += 1;
                        } else {
                            origEnd += 1;
                            normEnd += 1;
                        }
                    }
                    modifiedContent = originalContent.substring(0, origIdx) + newText + originalContent.substring(origEnd);
                } else {
                    // Fallback: show original vs original-with-new-text-appended
                    // so the user still sees the new_text being proposed
                    modifiedContent = originalContent + '\n// [edit_file: old_text not found in current file]\n' + newText;
                }
            } else {
                return; // Unsupported tool
            }

            // Store content in provider
            this.diffProvider.setContent(callId, 'original', originalContent);
            this.diffProvider.setContent(callId, 'modified', modifiedContent);

            // Build URIs
            const fileName = filePath.split(/[/\\]/).pop() || 'file';
            const originalUri = vscode.Uri.parse(`claraity-diff:/${callId}/original`);
            const modifiedUri = vscode.Uri.parse(`claraity-diff:/${callId}/modified`);

            const title = `${fileName} (${toolName})`;
            await vscode.commands.executeCommand('vscode.diff', originalUri, modifiedUri, title);
        } catch (err) {
            console.error('Failed to open diff editor:', err);
        }
    }

    private postToWebview(message: any): void {
        this.view?.webview.postMessage(message);
    }

    private getHtmlForWebview(webview: vscode.Webview): string {
        // Try to load built React app, fall back to inline HTML
        const webviewDistPath = vscode.Uri.joinPath(this.extensionUri, 'webview-ui', 'dist');
        const scriptFsPath = vscode.Uri.joinPath(webviewDistPath, 'webview.js').fsPath;

        const fs = require('fs');
        if (fs.existsSync(scriptFsPath)) {
            const scriptUri = webview.asWebviewUri(
                vscode.Uri.joinPath(webviewDistPath, 'webview.js')
            );
            const styleUri = webview.asWebviewUri(
                vscode.Uri.joinPath(webviewDistPath, 'webview.css')
            );

            return `<!DOCTYPE html>
<html lang="en">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <meta http-equiv="Content-Security-Policy" content="default-src 'none'; style-src ${webview.cspSource} 'unsafe-inline'; script-src ${webview.cspSource};">
    <link rel="stylesheet" href="${styleUri}">
    <title>ClarAIty</title>
</head>
<body>
    <div id="root"></div>
    <script src="${scriptUri}"></script>
</body>
</html>`;
        }

        // Fallback: inline chat UI (no React build needed for initial testing)
        return this.getInlineHtml(webview);
    }

    /**
     * Inline HTML chat UI with markdown rendering, syntax highlighting,
     * collapsible thinking blocks, and improved tool cards.
     *
     * Libraries: marked.js (markdown), highlight.js (syntax highlighting).
     * Both vendored in media/ to avoid network dependency.
     */
    private getInlineHtml(webview: vscode.Webview): string {
        // Webview URIs for vendored libraries
        const markedUri = webview.asWebviewUri(
            vscode.Uri.joinPath(this.extensionUri, 'media', 'marked.min.js')
        );
        const hljsUri = webview.asWebviewUri(
            vscode.Uri.joinPath(this.extensionUri, 'media', 'highlight.min.js')
        );
        const hljsCssUri = webview.asWebviewUri(
            vscode.Uri.joinPath(this.extensionUri, 'media', 'hljs-vscode.css')
        );

        return `<!DOCTYPE html>
<html lang="en">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <meta http-equiv="Content-Security-Policy" content="default-src 'none'; style-src ${webview.cspSource} 'unsafe-inline'; script-src ${webview.cspSource} 'unsafe-inline';">
    <title>ClarAIty</title>
    <link rel="stylesheet" href="${hljsCssUri}">
    <style>
        /* ── Base ── */
        * { box-sizing: border-box; margin: 0; padding: 0; }
        body {
            font-family: var(--vscode-font-family);
            font-size: var(--vscode-font-size);
            color: var(--vscode-foreground);
            background: var(--vscode-editor-background);
            height: 100vh;
            display: flex;
            flex-direction: column;
        }

        /* ── Status bar ── */
        #status-bar {
            padding: 4px 8px;
            font-size: 11px;
            color: var(--vscode-descriptionForeground);
            border-bottom: 1px solid var(--vscode-panel-border);
            display: flex;
            justify-content: space-between;
        }
        #status-bar .connected { color: var(--vscode-testing-iconPassed); }
        #status-bar .disconnected { color: var(--vscode-testing-iconFailed); }

        /* ── Context bar ── */
        #context-bar {
            padding: 2px 8px;
            font-size: 10px;
            color: var(--vscode-descriptionForeground);
        }
        #context-bar .bar {
            height: 3px;
            background: var(--vscode-progressBar-background);
            border-radius: 2px;
            margin-top: 2px;
            transition: width 0.3s;
        }

        /* ── Chat area ── */
        #chat-history {
            flex: 1;
            overflow-y: auto;
            padding: 8px;
        }

        /* ── Messages ── */
        .message {
            margin-bottom: 12px;
            padding: 8px;
            border-radius: 4px;
            word-break: break-word;
        }
        .message.user {
            white-space: pre-wrap;
            background: var(--vscode-input-background);
            border: 1px solid var(--vscode-input-border);
        }
        .message.assistant {
            background: var(--vscode-editor-background);
        }
        .message .role {
            font-weight: bold;
            font-size: 11px;
            margin-bottom: 4px;
            color: var(--vscode-descriptionForeground);
        }

        /* ── Markdown content ── */
        .message.assistant .content h1,
        .message.assistant .content h2,
        .message.assistant .content h3,
        .message.assistant .content h4 {
            margin-top: 12px;
            margin-bottom: 6px;
            font-weight: 600;
        }
        .message.assistant .content h1 { font-size: 1.3em; }
        .message.assistant .content h2 { font-size: 1.15em; }
        .message.assistant .content h3 { font-size: 1.05em; }
        .message.assistant .content p {
            margin: 6px 0;
            line-height: 1.5;
        }
        .message.assistant .content ul,
        .message.assistant .content ol {
            margin: 6px 0 6px 20px;
        }
        .message.assistant .content li {
            margin: 2px 0;
            line-height: 1.5;
        }
        .message.assistant .content blockquote {
            border-left: 3px solid var(--vscode-textBlockQuote-border);
            padding: 4px 12px;
            margin: 6px 0;
            color: var(--vscode-textBlockQuote-foreground);
            background: var(--vscode-textBlockQuote-background);
        }
        .message.assistant .content a {
            color: var(--vscode-textLink-foreground);
            text-decoration: none;
        }
        .message.assistant .content a:hover {
            text-decoration: underline;
        }
        .message.assistant .content hr {
            border: none;
            border-top: 1px solid var(--vscode-panel-border);
            margin: 12px 0;
        }
        .message.assistant .content table {
            border-collapse: collapse;
            margin: 8px 0;
            width: 100%;
        }
        .message.assistant .content th,
        .message.assistant .content td {
            border: 1px solid var(--vscode-panel-border);
            padding: 4px 8px;
            text-align: left;
        }
        .message.assistant .content th {
            background: var(--vscode-editor-inactiveSelectionBackground);
            font-weight: 600;
        }
        /* Inline code in markdown */
        .message.assistant .content code {
            background: var(--vscode-textCodeBlock-background);
            padding: 1px 4px;
            border-radius: 3px;
            font-family: var(--vscode-editor-font-family);
            font-size: 0.9em;
        }
        /* Override for code inside highlighted blocks */
        .message.assistant .content pre code {
            background: none;
            padding: 0;
        }
        /* Markdown-generated pre blocks (fenced code in markdown) */
        .message.assistant .content pre {
            background: var(--vscode-textCodeBlock-background);
            padding: 10px;
            border-radius: 4px;
            overflow-x: auto;
            margin: 8px 0;
            font-family: var(--vscode-editor-font-family);
            font-size: 0.9em;
            line-height: 1.4;
        }

        /* ── Streamed code blocks (siblings of .content) ── */
        .code-block-wrapper {
            margin: 8px 0;
            border: 1px solid var(--vscode-panel-border);
            border-radius: 4px;
            overflow: hidden;
        }
        .code-block-header {
            display: flex;
            justify-content: space-between;
            align-items: center;
            padding: 4px 10px;
            background: var(--vscode-editor-inactiveSelectionBackground);
            font-size: 11px;
            color: var(--vscode-descriptionForeground);
        }
        .code-block-header .lang-label {
            font-weight: 600;
            text-transform: uppercase;
            letter-spacing: 0.5px;
        }
        .code-block-header .copy-btn {
            background: none;
            border: 1px solid var(--vscode-panel-border);
            color: var(--vscode-descriptionForeground);
            padding: 2px 8px;
            border-radius: 2px;
            cursor: pointer;
            font-size: 11px;
            font-family: var(--vscode-font-family);
        }
        .code-block-header .copy-btn:hover {
            background: var(--vscode-toolbar-hoverBackground);
            color: var(--vscode-foreground);
        }
        .code-block-wrapper pre {
            margin: 0;
            padding: 10px;
            background: var(--vscode-textCodeBlock-background);
            overflow-x: auto;
        }
        .code-block-wrapper pre code {
            font-family: var(--vscode-editor-font-family);
            font-size: var(--vscode-editor-font-size, 13px);
            line-height: 1.4;
            background: none;
            padding: 0;
        }

        /* ── Thinking blocks ── */
        .thinking-block {
            margin: 6px 0;
            border: 1px solid var(--vscode-panel-border);
            border-radius: 4px;
            overflow: hidden;
        }
        .thinking-block summary {
            padding: 4px 10px;
            font-size: 11px;
            color: var(--vscode-descriptionForeground);
            cursor: pointer;
            background: var(--vscode-editor-inactiveSelectionBackground);
            user-select: none;
        }
        .thinking-block summary:hover {
            background: var(--vscode-toolbar-hoverBackground);
        }
        .thinking-block .thinking-content {
            padding: 8px 10px;
            font-size: 12px;
            color: var(--vscode-descriptionForeground);
            white-space: pre-wrap;
            max-height: 300px;
            overflow-y: auto;
            line-height: 1.4;
        }

        /* ── Tool cards ── */
        .tool-card {
            margin: 8px 0;
            border: 1px solid var(--vscode-panel-border);
            border-radius: 4px;
            background: var(--vscode-editor-inactiveSelectionBackground);
            overflow: hidden;
        }
        .tool-card .tool-header {
            display: flex;
            align-items: center;
            gap: 6px;
            padding: 6px 10px;
            font-size: 12px;
        }
        .tool-card .tool-icon {
            font-family: var(--vscode-editor-font-family);
            font-weight: bold;
            font-size: 11px;
            padding: 1px 4px;
            border-radius: 2px;
            background: var(--vscode-badge-background);
            color: var(--vscode-badge-foreground);
        }
        .tool-card .tool-name {
            font-weight: 600;
            flex: 1;
        }
        .tool-card .tool-duration {
            font-size: 10px;
            color: var(--vscode-descriptionForeground);
        }
        .tool-card .tool-badge {
            font-size: 10px;
            padding: 1px 6px;
            border-radius: 8px;
            font-weight: 600;
        }
        .tool-badge.pending { background: var(--vscode-editor-inactiveSelectionBackground); color: var(--vscode-descriptionForeground); }
        .tool-badge.running { background: var(--vscode-progressBar-background); color: var(--vscode-button-foreground); }
        .tool-badge.success { background: var(--vscode-testing-iconPassed); color: #fff; }
        .tool-badge.error { background: var(--vscode-testing-iconFailed); color: #fff; }
        .tool-badge.awaiting_approval { background: var(--vscode-editorWarning-foreground); color: #fff; }
        .tool-badge.approved { background: var(--vscode-testing-iconPassed); color: #fff; }
        .tool-badge.rejected { background: var(--vscode-testing-iconFailed); color: #fff; }
        .tool-badge.timeout { background: var(--vscode-editorWarning-foreground); color: #fff; }
        .tool-badge.cancelled { background: var(--vscode-descriptionForeground); color: #fff; }
        .tool-badge.skipped { background: var(--vscode-descriptionForeground); color: #fff; }
        .tool-card .tool-args {
            padding: 4px 10px;
            font-size: 11px;
            color: var(--vscode-descriptionForeground);
            font-family: var(--vscode-editor-font-family);
            border-top: 1px solid var(--vscode-panel-border);
            white-space: nowrap;
            overflow: hidden;
            text-overflow: ellipsis;
        }
        .tool-card .tool-result-details {
            border-top: 1px solid var(--vscode-panel-border);
        }
        .tool-card .tool-result-details summary {
            padding: 4px 10px;
            font-size: 11px;
            color: var(--vscode-descriptionForeground);
            cursor: pointer;
        }
        .tool-card .tool-result-details .result-body {
            padding: 6px 10px;
            font-size: 11px;
            font-family: var(--vscode-editor-font-family);
            white-space: pre-wrap;
            max-height: 200px;
            overflow-y: auto;
            color: var(--vscode-descriptionForeground);
        }
        .approval-buttons {
            margin: 0;
            padding: 6px 10px;
            display: flex;
            gap: 6px;
            border-top: 1px solid var(--vscode-panel-border);
        }
        .approval-buttons button {
            padding: 4px 12px;
            border: none;
            border-radius: 2px;
            cursor: pointer;
            font-size: 12px;
        }
        .btn-approve {
            background: var(--vscode-button-background);
            color: var(--vscode-button-foreground);
        }
        .btn-reject {
            background: var(--vscode-button-secondaryBackground);
            color: var(--vscode-button-secondaryForeground);
        }

        /* ── Subagent containers (nested inside delegation cards) ── */
        .subagent-details {
            border-top: 1px solid var(--vscode-panel-border);
        }
        .subagent-details summary {
            padding: 4px 10px;
            font-size: 11px;
            color: var(--vscode-descriptionForeground);
            cursor: pointer;
            user-select: none;
        }
        .subagent-details summary:hover {
            color: var(--vscode-foreground);
        }
        /* When no <summary> is present, hide the default disclosure marker */
        .subagent-details:not(:has(summary)) {
            list-style: none;
        }
        .subagent-details:not(:has(summary))::-webkit-details-marker {
            display: none;
        }
        .subagent-details .subagent-body {
            border-top: 1px solid var(--vscode-panel-border);
        }
        .subagent-details .subagent-body .tool-card {
            margin: 4px 6px;
            font-size: 11px;
        }
        .subagent-text {
            padding: 4px 10px;
            font-size: 11px;
            color: var(--vscode-descriptionForeground);
            white-space: pre-wrap;
            word-break: break-word;
            max-height: 150px;
            overflow-y: auto;
        }
        .subagent-text.user {
            color: var(--vscode-textLink-foreground);
            font-style: italic;
        }

        /* ── Interactive widgets (shared) ── */
        .interactive-widget {
            margin: 8px 0;
            border-radius: 4px;
            overflow: hidden;
        }
        .interactive-widget .widget-header {
            display: flex;
            align-items: center;
            gap: 6px;
            padding: 8px 10px;
            font-weight: 600;
            font-size: 12px;
        }
        .interactive-widget .widget-body {
            padding: 8px 10px;
        }
        .interactive-widget .widget-actions {
            padding: 6px 10px;
            display: flex;
            gap: 6px;
            border-top: 1px solid var(--vscode-panel-border);
        }
        .interactive-widget .widget-actions button {
            padding: 4px 12px;
            border: none;
            border-radius: 2px;
            cursor: pointer;
            font-size: 12px;
        }
        .interactive-widget textarea {
            width: 100%;
            min-height: 36px;
            max-height: 80px;
            resize: vertical;
            background: var(--vscode-input-background);
            color: var(--vscode-input-foreground);
            border: 1px solid var(--vscode-input-border);
            border-radius: 2px;
            padding: 4px 6px;
            font-family: var(--vscode-font-family);
            font-size: var(--vscode-font-size);
            margin-top: 6px;
        }
        .interactive-widget .btn-primary {
            background: var(--vscode-button-background);
            color: var(--vscode-button-foreground);
        }
        .interactive-widget .btn-secondary {
            background: var(--vscode-button-secondaryBackground);
            color: var(--vscode-button-secondaryForeground);
        }
        .interactive-widget .btn-danger {
            background: var(--vscode-testing-iconFailed);
            color: #fff;
        }

        /* ── Pause widget ── */
        .pause-widget {
            border: 1px solid var(--vscode-editorWarning-foreground);
            background: var(--vscode-editor-background);
        }
        .pause-widget .widget-header {
            background: var(--vscode-editorWarning-foreground);
            color: #fff;
        }
        .pause-widget .reason {
            font-size: 12px;
            margin-bottom: 6px;
            line-height: 1.4;
        }
        .pause-widget .stats-row {
            display: flex;
            gap: 12px;
            font-size: 11px;
            color: var(--vscode-descriptionForeground);
            margin-bottom: 6px;
        }
        .pause-widget .stats-row span {
            white-space: nowrap;
        }
        .pause-widget .pending-list {
            font-size: 11px;
            color: var(--vscode-descriptionForeground);
            margin: 4px 0 4px 16px;
        }
        .pause-widget .pending-list li {
            margin: 2px 0;
        }
        .pause-widget .feedback-section {
            margin-top: 6px;
        }
        .pause-widget .feedback-toggle {
            font-size: 11px;
            color: var(--vscode-textLink-foreground);
            cursor: pointer;
            background: none;
            border: none;
            padding: 0;
            font-family: var(--vscode-font-family);
        }

        /* ── Clarify widget ── */
        .clarify-widget {
            border: 1px solid var(--vscode-focusBorder);
            background: var(--vscode-editor-background);
        }
        .clarify-widget .widget-header {
            background: var(--vscode-focusBorder);
            color: #fff;
        }
        .clarify-widget .context-text {
            font-size: 11px;
            color: var(--vscode-descriptionForeground);
            margin-bottom: 8px;
            line-height: 1.4;
        }
        .clarify-widget .question-group {
            margin-bottom: 10px;
        }
        .clarify-widget .question-label {
            font-size: 12px;
            font-weight: 600;
            margin-bottom: 4px;
        }
        .clarify-widget .option-row {
            display: flex;
            align-items: center;
            gap: 6px;
            padding: 2px 0;
            font-size: 12px;
        }
        .clarify-widget .option-row input[type="radio"],
        .clarify-widget .option-row input[type="checkbox"] {
            margin: 0;
        }

        /* ── Plan widget ── */
        .plan-widget {
            border: 1px solid var(--vscode-button-background);
            background: var(--vscode-editor-background);
        }
        .plan-widget .widget-header {
            background: var(--vscode-button-background);
            color: var(--vscode-button-foreground);
        }
        .plan-widget .plan-content {
            font-size: 12px;
            max-height: 400px;
            overflow-y: auto;
            line-height: 1.5;
        }
        .plan-widget .plan-content h1,
        .plan-widget .plan-content h2,
        .plan-widget .plan-content h3 {
            margin-top: 8px;
            margin-bottom: 4px;
        }
        .plan-widget .plan-content h1 { font-size: 1.2em; }
        .plan-widget .plan-content h2 { font-size: 1.1em; }
        .plan-widget .plan-content p { margin: 4px 0; }
        .plan-widget .plan-content ul,
        .plan-widget .plan-content ol {
            margin: 4px 0 4px 16px;
        }
        .plan-widget .plan-content code {
            background: var(--vscode-textCodeBlock-background);
            padding: 1px 4px;
            border-radius: 3px;
            font-family: var(--vscode-editor-font-family);
            font-size: 0.9em;
        }
        .plan-widget .plan-content pre {
            background: var(--vscode-textCodeBlock-background);
            padding: 8px;
            border-radius: 4px;
            overflow-x: auto;
            margin: 6px 0;
        }
        .plan-widget .plan-content pre code {
            background: none;
            padding: 0;
        }
        .plan-widget .truncation-note {
            font-size: 11px;
            color: var(--vscode-editorWarning-foreground);
            padding: 4px 10px;
            border-top: 1px solid var(--vscode-panel-border);
        }
        .plan-widget .feedback-section {
            margin-top: 6px;
        }

        /* ── Plan/Act toggle ── */
        #mode-toggle-group {
            display: flex;
            margin-left: 6px;
            border: 1px solid var(--vscode-panel-border);
            border-radius: 2px;
            overflow: hidden;
        }
        #mode-toggle-group button {
            background: var(--vscode-dropdown-background);
            color: var(--vscode-dropdown-foreground);
            border: none;
            padding: 1px 8px;
            font-size: 11px;
            cursor: pointer;
            font-family: var(--vscode-font-family);
        }
        #mode-toggle-group button.active {
            background: var(--vscode-button-background);
            color: var(--vscode-button-foreground);
        }

        /* ── Turn stats ── */
        .turn-stats {
            font-size: 10px;
            color: var(--vscode-descriptionForeground);
            text-align: right;
            margin-top: 4px;
            padding: 0 4px;
        }

        /* ── Todo panel ── */
        #todo-panel {
            border-bottom: 1px solid var(--vscode-panel-border);
            font-size: 12px;
            display: none;
        }
        #todo-header {
            display: flex;
            justify-content: space-between;
            align-items: center;
            padding: 4px 8px;
            cursor: pointer;
            user-select: none;
            color: var(--vscode-descriptionForeground);
        }
        #todo-header:hover {
            background: var(--vscode-toolbar-hoverBackground);
        }
        #todo-list {
            padding: 0 8px 4px;
        }
        #todo-panel.collapsed #todo-list {
            display: none;
        }
        .todo-item {
            display: flex;
            align-items: center;
            gap: 6px;
            padding: 2px 0;
            font-size: 11px;
        }
        .todo-item .todo-status {
            font-family: var(--vscode-editor-font-family);
            font-size: 10px;
            font-weight: bold;
            min-width: 32px;
        }
        .todo-item.in_progress .todo-status { color: var(--vscode-progressBar-background); }
        .todo-item.completed { color: var(--vscode-descriptionForeground); opacity: 0.6; }
        .todo-item.completed .todo-status { color: var(--vscode-testing-iconPassed); }

        /* ── Auto-approve panel ── */
        #auto-approve-panel {
            border-top: 1px solid var(--vscode-panel-border);
            font-size: 11px;
        }
        #auto-approve-header {
            display: flex;
            justify-content: space-between;
            align-items: center;
            padding: 3px 8px;
            cursor: pointer;
            user-select: none;
            color: var(--vscode-descriptionForeground);
        }
        #auto-approve-header:hover {
            background: var(--vscode-toolbar-hoverBackground);
        }
        #auto-approve-summary.has-active {
            color: var(--vscode-testing-iconPassed);
        }
        #auto-approve-body {
            padding: 4px 8px 6px;
            display: none;
        }
        #auto-approve-panel.expanded #auto-approve-body {
            display: block;
        }
        .aa-row {
            display: flex;
            align-items: center;
            gap: 6px;
            padding: 2px 0;
            cursor: pointer;
        }
        .aa-row input[type="checkbox"] { margin: 0; cursor: pointer; }

        /* ── Config panel ── */
        #config-gear {
            cursor: pointer;
            font-size: 14px;
            opacity: 0.7;
            user-select: none;
        }
        #config-gear:hover { opacity: 1; }
        #config-panel {
            display: none;
            border-bottom: 1px solid var(--vscode-panel-border);
            max-height: 70vh;
            overflow-y: auto;
        }
        #config-panel.visible { display: block; }
        #config-header {
            display: flex;
            justify-content: space-between;
            align-items: center;
            padding: 6px 8px;
            background: var(--vscode-editor-inactiveSelectionBackground);
            font-weight: 600;
            font-size: 12px;
        }
        #config-close {
            cursor: pointer;
            font-size: 14px;
            opacity: 0.7;
            background: none;
            border: none;
            color: var(--vscode-foreground);
        }
        #config-close:hover { opacity: 1; }
        .config-section {
            padding: 8px;
        }
        .config-section label {
            display: block;
            font-size: 11px;
            color: var(--vscode-descriptionForeground);
            margin: 6px 0 2px;
        }
        .config-section label:first-child { margin-top: 0; }
        .config-section input[type="text"],
        .config-section input[type="password"],
        .config-section input[type="number"],
        .config-section select {
            width: 100%;
            padding: 4px 6px;
            background: var(--vscode-input-background);
            color: var(--vscode-input-foreground);
            border: 1px solid var(--vscode-input-border);
            border-radius: 2px;
            font-family: var(--vscode-font-family);
            font-size: var(--vscode-font-size);
        }
        .config-row {
            display: flex;
            gap: 8px;
        }
        .config-row > div { flex: 1; }
        #cfg-model-list {
            max-height: 120px;
            overflow-y: auto;
            border: 1px solid var(--vscode-panel-border);
            border-radius: 2px;
            margin-top: 4px;
            display: none;
        }
        #cfg-model-list.visible { display: block; }
        .model-option {
            padding: 3px 8px;
            font-size: 11px;
            cursor: pointer;
            font-family: var(--vscode-editor-font-family);
        }
        .model-option:hover { background: var(--vscode-toolbar-hoverBackground); }
        .model-option.selected { background: var(--vscode-button-background); color: var(--vscode-button-foreground); }
        .cfg-subagent-row {
            display: flex;
            align-items: center;
            gap: 6px;
            margin: 3px 0;
        }
        .cfg-subagent-row label {
            min-width: 110px;
            margin: 0;
            font-size: 11px;
        }
        .cfg-subagent-row input { flex: 1; }
        #cfg-subagents-section { display: none; margin-top: 6px; }
        #cfg-subagents-section.visible { display: block; }
        #config-actions {
            display: flex;
            gap: 6px;
            padding: 6px 8px;
            border-top: 1px solid var(--vscode-panel-border);
        }
        #config-actions button {
            padding: 4px 12px;
            border: none;
            border-radius: 2px;
            cursor: pointer;
            font-size: 12px;
        }
        .cfg-btn-primary {
            background: var(--vscode-button-background);
            color: var(--vscode-button-foreground);
        }
        .cfg-btn-secondary {
            background: var(--vscode-button-secondaryBackground);
            color: var(--vscode-button-secondaryForeground);
        }
        #cfg-notification {
            padding: 4px 8px;
            font-size: 11px;
            display: none;
        }
        #cfg-notification.success { display: block; color: var(--vscode-testing-iconPassed); }
        #cfg-notification.error { display: block; color: var(--vscode-testing-iconFailed); }
        #cfg-fetch-btn {
            margin-top: 4px;
            padding: 3px 10px;
            font-size: 11px;
            background: var(--vscode-button-secondaryBackground);
            color: var(--vscode-button-secondaryForeground);
            border: none;
            border-radius: 2px;
            cursor: pointer;
        }
        #cfg-fetch-status {
            font-size: 11px;
            color: var(--vscode-descriptionForeground);
            margin-left: 6px;
        }
        #cfg-key-indicator {
            font-size: 10px;
            color: var(--vscode-descriptionForeground);
            margin-left: 4px;
        }
        #cfg-subagents-toggle {
            margin-top: 8px;
            padding: 3px 10px;
            font-size: 11px;
            background: var(--vscode-button-secondaryBackground);
            color: var(--vscode-button-secondaryForeground);
            border: none;
            border-radius: 2px;
            cursor: pointer;
        }
        #cfg-same-model-row {
            display: flex;
            align-items: center;
            gap: 6px;
            margin: 6px 0;
            font-size: 11px;
            color: var(--vscode-descriptionForeground);
        }

        /* ── Input area ── */
        #input-area {
            border-top: 1px solid var(--vscode-panel-border);
            padding: 8px;
            display: flex;
            gap: 4px;
        }
        #input-area textarea {
            flex: 1;
            resize: none;
            background: var(--vscode-input-background);
            color: var(--vscode-input-foreground);
            border: 1px solid var(--vscode-input-border);
            border-radius: 2px;
            padding: 6px;
            font-family: var(--vscode-font-family);
            font-size: var(--vscode-font-size);
            min-height: 36px;
            max-height: 120px;
        }
        #input-area button {
            padding: 6px 12px;
            background: var(--vscode-button-background);
            color: var(--vscode-button-foreground);
            border: none;
            border-radius: 2px;
            cursor: pointer;
            align-self: flex-end;
        }
        #input-area button:disabled {
            opacity: 0.5;
            cursor: not-allowed;
        }
    </style>
</head>
<body>
    <div id="status-bar">
        <span id="connection-status" class="disconnected">Disconnected</span>
        <span id="model-name"></span>
        <div id="mode-toggle-group">
            <button id="mode-plan-btn">Plan</button>
            <button id="mode-act-btn" class="active">Act</button>
        </div>
        <span id="new-chat-btn" title="New Chat" style="cursor:pointer;font-size:14px;opacity:0.7;user-select:none;margin-left:6px;">+</span>
        <span id="config-gear" title="LLM Configuration">\u2699</span>
    </div>
    <div id="config-panel">
        <div id="config-header">
            <span>LLM Configuration</span>
            <button id="config-close">\u2715</button>
        </div>
        <div id="cfg-notification"></div>
        <div class="config-section">
            <label>Backend</label>
            <select id="cfg-backend">
                <option value="openai">openai</option>
                <option value="anthropic">anthropic</option>
                <option value="ollama">ollama</option>
            </select>

            <label>API URL</label>
            <input type="text" id="cfg-base-url" placeholder="http://localhost:8000/v1" />

            <label>API Key <span id="cfg-key-indicator"></span></label>
            <input type="password" id="cfg-api-key" placeholder="Enter new API key..." />

            <label>Model</label>
            <input type="text" id="cfg-model" placeholder="Model name" />
            <div>
                <button id="cfg-fetch-btn">Fetch Models</button>
                <span id="cfg-fetch-status"></span>
            </div>
            <div id="cfg-model-list"></div>

            <div class="config-row">
                <div>
                    <label>Temperature</label>
                    <input type="number" id="cfg-temperature" step="0.05" min="0" max="2" />
                </div>
                <div>
                    <label>Max Tokens</label>
                    <input type="number" id="cfg-max-tokens" min="1" />
                </div>
            </div>
            <div class="config-row">
                <div>
                    <label>Context Window</label>
                    <input type="number" id="cfg-context-window" min="1" />
                </div>
                <div>
                    <label>Thinking Budget</label>
                    <input type="number" id="cfg-thinking-budget" min="0" placeholder="(none)" />
                </div>
            </div>

            <button id="cfg-subagents-toggle">+ Subagent Models</button>
            <div id="cfg-subagents-section">
                <div id="cfg-same-model-row">
                    <input type="checkbox" id="cfg-same-model" />
                    <label for="cfg-same-model" style="margin:0;display:inline;">Use same model for all</label>
                </div>
                <div id="cfg-subagent-inputs"></div>
            </div>
        </div>
        <div id="config-actions">
            <button id="cfg-save-btn" class="cfg-btn-primary">Save</button>
            <button id="cfg-cancel-btn" class="cfg-btn-secondary">Cancel</button>
        </div>
    </div>
    <div id="todo-panel" class="collapsed">
        <div id="todo-header">
            <span id="todo-summary">Tasks: 0 active</span>
            <span id="todo-toggle">+</span>
        </div>
        <div id="todo-list"></div>
    </div>
    <div id="context-bar" style="display:none">
        <span id="context-text"></span>
        <div class="bar" id="context-bar-fill" style="width:0%"></div>
    </div>
    <div id="chat-history"></div>
    <div id="auto-approve-panel">
        <div id="auto-approve-header">
            <span id="auto-approve-summary">Auto-approve</span>
            <span id="aa-toggle-icon">+</span>
        </div>
        <div id="auto-approve-body">
            <label class="aa-row"><input type="checkbox" id="aa-edit" /> Edit files</label>
            <label class="aa-row"><input type="checkbox" id="aa-execute" /> Run commands</label>
            <label class="aa-row"><input type="checkbox" id="aa-browser" /> Browser tools</label>
        </div>
    </div>
    <div id="input-area">
        <textarea id="chat-input" placeholder="Ask ClarAIty..." rows="1"></textarea>
        <button id="send-btn">Send</button>
    </div>

    <script src="${markedUri}"></script>
    <script src="${hljsUri}"></script>
    <script>
        // ── VS Code API ──
        const vscode = acquireVsCodeApi();

        // ── State ──
        let isStreaming = false;
        let currentAssistantDiv = null;   // The .message.assistant wrapper
        let currentContentDiv = null;     // Current .content div (text goes here)
        let currentCodeElement = null;    // Current <code> inside a code block
        let currentThinkingBlock = null;  // Current <details> for thinking
        let markdownBuffer = '';          // Accumulated markdown text for re-render
        let renderScheduled = false;      // Throttle flag for markdown re-render
        let userScrolledUp = false;       // Auto-scroll lock
        const toolCards = {};             // call_id -> DOM element
        const toolMeta = {};              // call_id -> { name, arguments } (cached from first update)
        const subagentContainers = {};    // subagent_id -> { details, body, summary, toolCount }
        const subagentParents = {};       // subagent_id -> parent_tool_call_id

        // Tool icon mapping
        const TOOL_ICONS = {
            read_file: 'R',
            write_file: 'W',
            edit_file: 'E',
            run_command: '>',
            list_directory: 'D',
            search_files: '?',
            clarify: 'Q',
            plan: 'P',
            delegate_task: 'T',
            delegate_to_subagent: 'SA',
        };

        // ── DOM refs ──
        const chatHistory = document.getElementById('chat-history');
        const chatInput = document.getElementById('chat-input');
        const sendBtn = document.getElementById('send-btn');
        const connectionStatus = document.getElementById('connection-status');
        const modelName = document.getElementById('model-name');
        const modePlanBtn = document.getElementById('mode-plan-btn');
        const modeActBtn = document.getElementById('mode-act-btn');
        const contextBar = document.getElementById('context-bar');
        const contextText = document.getElementById('context-text');
        const contextBarFill = document.getElementById('context-bar-fill');
        const todoPanel = document.getElementById('todo-panel');
        const todoSummary = document.getElementById('todo-summary');
        const todoToggleIcon = document.getElementById('todo-toggle');
        const todoList = document.getElementById('todo-list');
        const autoApprovePanel = document.getElementById('auto-approve-panel');
        const autoApproveHeader = document.getElementById('auto-approve-header');
        const autoApproveSummary = document.getElementById('auto-approve-summary');
        const aaToggleIcon = document.getElementById('aa-toggle-icon');
        const aaEdit = document.getElementById('aa-edit');
        const aaExecute = document.getElementById('aa-execute');
        const aaBrowser = document.getElementById('aa-browser');

        let currentMode = 'normal';
        let currentSessionId = null;

        // ── New Chat button ──
        document.getElementById('new-chat-btn').addEventListener('click', () => {
            vscode.postMessage({ type: 'newSession' });
        });

        // ── Auto-scroll ──
        chatHistory.addEventListener('scroll', () => {
            const atBottom = chatHistory.scrollHeight - chatHistory.scrollTop - chatHistory.clientHeight < 40;
            userScrolledUp = !atBottom;
        });

        function scrollToBottom() {
            if (!userScrolledUp) {
                chatHistory.scrollTop = chatHistory.scrollHeight;
            }
        }

        // ── Interrupt stream (Escape key) ──
        document.addEventListener('keydown', (e) => {
            if (e.key === 'Escape' && isStreaming) {
                e.preventDefault();
                vscode.postMessage({ type: 'interrupt' });
            }
        });

        // ── Send message ──
        function sendMessage() {
            const content = chatInput.value.trim();
            if (!content || isStreaming) return;

            addMessage('user', content);
            chatInput.value = '';
            chatInput.style.height = 'auto';

            vscode.postMessage({ type: 'chatMessage', content });
        }

        sendBtn.addEventListener('click', sendMessage);
        chatInput.addEventListener('keydown', (e) => {
            if (e.key === 'Enter' && !e.shiftKey) {
                e.preventDefault();
                sendMessage();
            }
        });

        // Auto-resize textarea
        chatInput.addEventListener('input', () => {
            chatInput.style.height = 'auto';
            chatInput.style.height = Math.min(chatInput.scrollHeight, 120) + 'px';
        });

        // ── Helpers ──
        function escapeHtml(text) {
            const div = document.createElement('div');
            div.textContent = text;
            return div.innerHTML;
        }

        function getPrimaryArg(toolName, args) {
            if (!args) return '';
            if (toolName === 'run_command') return args.command || '';
            if (args.path) return args.path;
            if (args.file_path) return args.file_path;
            if (args.query) return args.query;
            if (args.directory) return args.directory;
            // Fallback: first string value
            for (const v of Object.values(args)) {
                if (typeof v === 'string' && v.length < 200) return v;
            }
            return '';
        }

        // ── Message creation ──
        function addMessage(role, content) {
            const div = document.createElement('div');
            div.className = 'message ' + role;
            div.innerHTML = '<div class="role">' + role + '</div><div class="content">' + escapeHtml(content) + '</div>';
            chatHistory.appendChild(div);
            scrollToBottom();
            return div;
        }

        function startAssistantMessage() {
            currentAssistantDiv = document.createElement('div');
            currentAssistantDiv.className = 'message assistant';
            currentAssistantDiv.innerHTML = '<div class="role">assistant</div>';
            currentContentDiv = document.createElement('div');
            currentContentDiv.className = 'content';
            currentAssistantDiv.appendChild(currentContentDiv);
            chatHistory.appendChild(currentAssistantDiv);
            markdownBuffer = '';
            currentCodeElement = null;
            currentThinkingBlock = null;
        }

        // ── Markdown rendering ──
        // Configure marked to not process code blocks (we handle them via stream events)
        if (typeof marked !== 'undefined') {
            marked.setOptions({
                breaks: true,
                gfm: true,
            });
        }

        function renderMarkdown() {
            if (!currentContentDiv || !markdownBuffer) return;
            try {
                currentContentDiv.innerHTML = marked.parse(markdownBuffer);
                // Highlight any code blocks that came through markdown (e.g. inline backticks
                // won't have hljs, but fenced blocks in the markdown buffer will)
                currentContentDiv.querySelectorAll('pre code').forEach((block) => {
                    if (typeof hljs !== 'undefined') {
                        hljs.highlightElement(block);
                    }
                });
            } catch (e) {
                // Fallback: raw text
                currentContentDiv.textContent = markdownBuffer;
            }
            scrollToBottom();
        }

        function scheduleRender() {
            if (renderScheduled) return;
            renderScheduled = true;
            requestAnimationFrame(() => {
                renderScheduled = false;
                renderMarkdown();
            });
        }

        function appendText(text) {
            if (!currentContentDiv) {
                startAssistantMessage();
            }
            markdownBuffer += text;
            scheduleRender();
        }

        // Flush pending markdown, then start a fresh content div
        function flushAndNewContentDiv() {
            renderMarkdown();
            currentContentDiv = document.createElement('div');
            currentContentDiv.className = 'content';
            currentAssistantDiv.appendChild(currentContentDiv);
            markdownBuffer = '';
        }

        // ── Code blocks ──
        function startCodeBlock(language) {
            if (!currentAssistantDiv) startAssistantMessage();

            // Flush any pending text
            flushAndNewContentDiv();

            const wrapper = document.createElement('div');
            wrapper.className = 'code-block-wrapper';

            const header = document.createElement('div');
            header.className = 'code-block-header';

            const langLabel = document.createElement('span');
            langLabel.className = 'lang-label';
            langLabel.textContent = language || 'code';
            header.appendChild(langLabel);

            const copyBtn = document.createElement('button');
            copyBtn.className = 'copy-btn';
            copyBtn.textContent = 'Copy';
            copyBtn.addEventListener('click', () => {
                const code = wrapper.querySelector('code').textContent;
                vscode.postMessage({ type: 'copyToClipboard', text: code });
                copyBtn.textContent = 'Copied!';
                setTimeout(() => { copyBtn.textContent = 'Copy'; }, 1500);
            });
            header.appendChild(copyBtn);

            wrapper.appendChild(header);

            const pre = document.createElement('pre');
            const code = document.createElement('code');
            if (language) {
                code.className = 'language-' + language;
            }
            pre.appendChild(code);
            wrapper.appendChild(pre);

            // Insert wrapper as sibling after current content div
            currentAssistantDiv.appendChild(wrapper);
            currentCodeElement = code;
        }

        function appendCodeDelta(text) {
            if (currentCodeElement) {
                currentCodeElement.textContent += text;
                scrollToBottom();
            }
        }

        function endCodeBlock() {
            if (currentCodeElement && typeof hljs !== 'undefined') {
                hljs.highlightElement(currentCodeElement);
            }
            currentCodeElement = null;

            // Create fresh content div for subsequent text
            currentContentDiv = document.createElement('div');
            currentContentDiv.className = 'content';
            currentAssistantDiv.appendChild(currentContentDiv);
            markdownBuffer = '';
            scrollToBottom();
        }

        // ── Thinking blocks ──
        function startThinking() {
            if (!currentAssistantDiv) startAssistantMessage();
            flushAndNewContentDiv();

            const details = document.createElement('details');
            details.className = 'thinking-block';

            const summary = document.createElement('summary');
            summary.textContent = 'Thinking...';
            details.appendChild(summary);

            const content = document.createElement('div');
            content.className = 'thinking-content';
            details.appendChild(content);

            currentAssistantDiv.appendChild(details);
            currentThinkingBlock = details;
        }

        function appendThinking(text) {
            if (currentThinkingBlock) {
                const content = currentThinkingBlock.querySelector('.thinking-content');
                content.textContent += text;
                scrollToBottom();
            }
        }

        function endThinking(tokenCount) {
            if (currentThinkingBlock) {
                const summary = currentThinkingBlock.querySelector('summary');
                const label = tokenCount ? 'Thought (' + tokenCount + ' tokens)' : 'Thought';
                summary.textContent = label;
                currentThinkingBlock = null;
            }

            // Fresh content div after thinking
            currentContentDiv = document.createElement('div');
            currentContentDiv.className = 'content';
            currentAssistantDiv.appendChild(currentContentDiv);
            markdownBuffer = '';
        }

        // ── Mode display ──
        function updateModeDisplay(mode) {
            currentMode = mode || 'normal';
            if (currentMode === 'plan') {
                modePlanBtn.classList.add('active');
                modeActBtn.classList.remove('active');
            } else {
                modePlanBtn.classList.remove('active');
                modeActBtn.classList.add('active');
            }
        }

        // Plan/Act toggle click handlers
        modePlanBtn.addEventListener('click', () => {
            vscode.postMessage({ type: 'setMode', mode: 'plan' });
        });
        modeActBtn.addEventListener('click', () => {
            vscode.postMessage({ type: 'setMode', mode: 'normal' });
        });

        // ── Auto-approve panel ──
        autoApproveHeader.addEventListener('click', () => {
            autoApprovePanel.classList.toggle('expanded');
            aaToggleIcon.textContent = autoApprovePanel.classList.contains('expanded') ? '-' : '+';
        });

        function sendAutoApprove() {
            vscode.postMessage({
                type: 'setAutoApprove',
                categories: { edit: aaEdit.checked, execute: aaExecute.checked, browser: aaBrowser.checked }
            });
        }
        aaEdit.addEventListener('change', sendAutoApprove);
        aaExecute.addEventListener('change', sendAutoApprove);
        aaBrowser.addEventListener('change', sendAutoApprove);

        function updateAutoApproveDisplay(categories) {
            if (!categories) return;
            aaEdit.checked = !!categories.edit;
            aaExecute.checked = !!categories.execute;
            aaBrowser.checked = !!categories.browser;
            // Update summary text
            const active = Object.entries(categories).filter(([,v]) => v).map(([k]) =>
                k === 'edit' ? 'Edit' : k === 'execute' ? 'Commands' : 'Browser'
            );
            autoApproveSummary.textContent = active.length > 0
                ? 'Auto-approve: ' + active.join(', ')
                : 'Auto-approve';
            autoApproveSummary.className = active.length > 0 ? 'has-active' : '';
        }

        // ── Turn stats ──
        function showTurnStats(tokens, durationMs) {
            if (!currentAssistantDiv) return;
            const parts = [];
            if (tokens != null) parts.push(tokens.toLocaleString() + ' tokens');
            if (durationMs != null) parts.push((durationMs / 1000).toFixed(1) + 's');
            if (parts.length === 0) return;

            const statsDiv = document.createElement('div');
            statsDiv.className = 'turn-stats';
            statsDiv.textContent = parts.join(' | ');
            currentAssistantDiv.appendChild(statsDiv);
        }

        // ── Todo panel ──
        function toggleTodoPanel() {
            todoPanel.classList.toggle('collapsed');
            todoToggleIcon.textContent = todoPanel.classList.contains('collapsed') ? '+' : '-';
        }
        document.getElementById('todo-header').addEventListener('click', toggleTodoPanel);

        function updateTodos(todos) {
            if (!todos || todos.length === 0) {
                todoPanel.style.display = 'none';
                return;
            }
            todoPanel.style.display = 'block';

            // Summary
            const active = todos.filter(t => t.status === 'in_progress').length;
            const completed = todos.filter(t => t.status === 'completed').length;
            const total = todos.length;
            todoSummary.textContent = 'Tasks: ' + active + ' active, ' + completed + '/' + total + ' done';

            // List
            todoList.innerHTML = '';
            for (const todo of todos) {
                const item = document.createElement('div');
                item.className = 'todo-item ' + (todo.status || 'pending');

                const statusSpan = document.createElement('span');
                statusSpan.className = 'todo-status';
                if (todo.status === 'in_progress') statusSpan.textContent = '[>>>]';
                else if (todo.status === 'completed') statusSpan.textContent = '[x]';
                else statusSpan.textContent = '[ ]';
                item.appendChild(statusSpan);

                const textSpan = document.createElement('span');
                // For in_progress, show activeForm if available
                textSpan.textContent = (todo.status === 'in_progress' && todo.activeForm)
                    ? todo.activeForm
                    : (todo.subject || todo.content || '');
                item.appendChild(textSpan);

                todoList.appendChild(item);
            }
        }

        // ── Tool cards ──
        function updateToolCard(data, subagentId) {
            // Cache metadata from the first update that carries it
            if (!toolMeta[data.call_id]) {
                toolMeta[data.call_id] = {};
            }
            const meta = toolMeta[data.call_id];
            if (data.tool_name) meta.name = data.tool_name;
            if (data.arguments) meta.arguments = data.arguments;

            let card = toolCards[data.call_id];
            if (!card) {
                if (!currentAssistantDiv) startAssistantMessage();

                // Flush pending text before the tool card (mirrors TUI segments)
                renderMarkdown();

                card = document.createElement('div');
                card.className = 'tool-card';
                card.innerHTML = [
                    '<div class="tool-header">',
                    '  <span class="tool-icon"></span>',
                    '  <span class="tool-name"></span>',
                    '  <span class="tool-duration"></span>',
                    '  <span class="tool-badge"></span>',
                    '</div>',
                ].join('');
                toolCards[data.call_id] = card;

                // Route into subagent container or main assistant div
                const saInfo = subagentId && subagentContainers[subagentId];
                if (saInfo) {
                    saInfo.body.appendChild(card);
                    saInfo.toolCount++;
                } else {
                    currentAssistantDiv.appendChild(card);
                    // Create fresh content div after the card so subsequent
                    // text renders below it (same as TUI's segment reset)
                    currentContentDiv = document.createElement('div');
                    currentContentDiv.className = 'content';
                    currentAssistantDiv.appendChild(currentContentDiv);
                    markdownBuffer = '';
                }
            }

            // Header — use cached name (survives across status updates)
            const icon = card.querySelector('.tool-icon');
            const name = card.querySelector('.tool-name');
            const duration = card.querySelector('.tool-duration');
            const badge = card.querySelector('.tool-badge');

            const toolName = meta.name || data.tool_name || 'tool';
            icon.textContent = TOOL_ICONS[toolName] || 'T';
            // Don't overwrite name for delegation cards — subagent:registered sets the real name+model
            if (toolName !== 'delegate_to_subagent' || !name.textContent || name.textContent === toolName) {
                name.textContent = toolName;
            }
            badge.textContent = data.status;
            badge.className = 'tool-badge ' + data.status;

            if (data.duration_ms) {
                duration.textContent = data.duration_ms + 'ms';
            }

            // Args row — use cached arguments (skip for delegation — shown in header via subagent:registered)
            const primaryArg = toolName === 'delegate_to_subagent'
                ? ''
                : getPrimaryArg(toolName, meta.arguments || data.arguments);
            let argsRow = card.querySelector('.tool-args');
            if (primaryArg && !argsRow) {
                argsRow = document.createElement('div');
                argsRow.className = 'tool-args';
                // Insert after header
                const header = card.querySelector('.tool-header');
                header.after(argsRow);
            }
            if (argsRow && primaryArg) {
                argsRow.textContent = primaryArg;
                argsRow.title = primaryArg;
            }

            // Auto-open diff for write_file/edit_file on awaiting_approval
            if (data.status === 'awaiting_approval'
                && (toolName === 'write_file' || toolName === 'edit_file')
                && meta.arguments) {
                vscode.postMessage({
                    type: 'showDiff',
                    callId: data.call_id,
                    toolName: toolName,
                    arguments: meta.arguments,
                });
            }

            // Approval buttons + feedback
            let approvalSection = card.querySelector('.approval-section');
            if (data.status === 'awaiting_approval') {
                if (!approvalSection) {
                    approvalSection = document.createElement('div');
                    approvalSection.className = 'approval-section';
                    card.appendChild(approvalSection);
                }
                approvalSection.style.display = 'block';
                approvalSection.innerHTML = '';

                // Buttons row
                const buttons = document.createElement('div');
                buttons.className = 'approval-buttons';
                buttons.style.display = 'flex';

                const approveBtn = document.createElement('button');
                approveBtn.className = 'btn-approve';
                approveBtn.textContent = 'Accept';
                approveBtn.addEventListener('click', () => {
                    vscode.postMessage({ type: 'approvalResult', callId: data.call_id, approved: true });
                });
                buttons.appendChild(approveBtn);

                const rejectBtn = document.createElement('button');
                rejectBtn.className = 'btn-reject';
                rejectBtn.textContent = 'Reject';
                rejectBtn.addEventListener('click', () => {
                    const feedback = feedbackInput.value.trim() || undefined;
                    vscode.postMessage({ type: 'approvalResult', callId: data.call_id, approved: false, feedback: feedback });
                });
                buttons.appendChild(rejectBtn);

                approvalSection.appendChild(buttons);

                // Feedback textarea (always visible)
                const feedbackWrap = document.createElement('div');
                feedbackWrap.style.cssText = 'padding:6px 10px;';
                const feedbackInput = document.createElement('textarea');
                feedbackInput.placeholder = 'Feedback for the agent (sent with Reject)...';
                feedbackInput.style.cssText = 'width:100%;min-height:32px;max-height:80px;resize:vertical;background:var(--vscode-input-background);color:var(--vscode-input-foreground);border:1px solid var(--vscode-input-border);border-radius:2px;padding:4px 6px;font-family:var(--vscode-font-family);font-size:var(--vscode-font-size);';
                feedbackWrap.appendChild(feedbackInput);
                approvalSection.appendChild(feedbackWrap);
            } else if (approvalSection) {
                approvalSection.style.display = 'none';
            }

            // Expandable result
            if (data.result) {
                let resultDetails = card.querySelector('.tool-result-details');
                if (!resultDetails) {
                    resultDetails = document.createElement('details');
                    resultDetails.className = 'tool-result-details';
                    const rSummary = document.createElement('summary');
                    rSummary.textContent = 'Result';
                    resultDetails.appendChild(rSummary);
                    const rBody = document.createElement('div');
                    rBody.className = 'result-body';
                    resultDetails.appendChild(rBody);
                    card.appendChild(resultDetails);
                }
                const rBody = resultDetails.querySelector('.result-body');
                rBody.textContent = String(data.result);
            }

            scrollToBottom();
        }

        // ── Pause/Continue Widget ──
        function showPausePrompt(payload) {
            if (!currentAssistantDiv) startAssistantMessage();
            // Remove any existing pause widget
            removePausePrompt();

            const widget = document.createElement('div');
            widget.className = 'interactive-widget pause-widget';
            widget.id = 'pause-widget';

            // Header
            const header = document.createElement('div');
            header.className = 'widget-header';
            header.textContent = 'Agent Paused';
            widget.appendChild(header);

            // Body
            const body = document.createElement('div');
            body.className = 'widget-body';

            // Reason
            const reason = document.createElement('div');
            reason.className = 'reason';
            reason.textContent = payload.reason || 'Agent has paused.';
            body.appendChild(reason);

            // Stats row
            if (payload.stats && typeof payload.stats === 'object') {
                const statsRow = document.createElement('div');
                statsRow.className = 'stats-row';
                for (const [key, val] of Object.entries(payload.stats)) {
                    const span = document.createElement('span');
                    span.textContent = key.replace(/_/g, ' ') + ': ' + val;
                    statsRow.appendChild(span);
                }
                body.appendChild(statsRow);
            }

            // Pending todos
            if (payload.pending_todos && payload.pending_todos.length > 0) {
                const listLabel = document.createElement('div');
                listLabel.style.fontSize = '11px';
                listLabel.style.color = 'var(--vscode-descriptionForeground)';
                listLabel.textContent = 'Pending tasks:';
                body.appendChild(listLabel);

                const list = document.createElement('ol');
                list.className = 'pending-list';
                for (const todo of payload.pending_todos) {
                    const li = document.createElement('li');
                    li.textContent = todo;
                    list.appendChild(li);
                }
                body.appendChild(list);
            }

            // Feedback section (expandable)
            const feedbackSection = document.createElement('div');
            feedbackSection.className = 'feedback-section';
            feedbackSection.style.display = 'none';
            const feedbackArea = document.createElement('textarea');
            feedbackArea.placeholder = 'Optional: add guidance for the agent...';
            feedbackSection.appendChild(feedbackArea);

            const feedbackToggle = document.createElement('button');
            feedbackToggle.className = 'feedback-toggle';
            feedbackToggle.textContent = '+ Add feedback';
            feedbackToggle.addEventListener('click', () => {
                const visible = feedbackSection.style.display !== 'none';
                feedbackSection.style.display = visible ? 'none' : 'block';
                feedbackToggle.textContent = visible ? '+ Add feedback' : '- Hide feedback';
            });
            body.appendChild(feedbackToggle);
            body.appendChild(feedbackSection);

            widget.appendChild(body);

            // Actions
            const actions = document.createElement('div');
            actions.className = 'widget-actions';

            const continueBtn = document.createElement('button');
            continueBtn.className = 'btn-primary';
            continueBtn.textContent = 'Continue';
            continueBtn.addEventListener('click', () => {
                const feedback = feedbackArea.value.trim() || null;
                vscode.postMessage({ type: 'pauseResult', continueWork: true, feedback: feedback });
                removePausePrompt();
            });
            actions.appendChild(continueBtn);

            const stopBtn = document.createElement('button');
            stopBtn.className = 'btn-danger';
            stopBtn.textContent = 'Stop';
            stopBtn.addEventListener('click', () => {
                const feedback = feedbackArea.value.trim() || null;
                vscode.postMessage({ type: 'pauseResult', continueWork: false, feedback: feedback });
                removePausePrompt();
            });
            actions.appendChild(stopBtn);

            widget.appendChild(actions);

            currentAssistantDiv.appendChild(widget);
            scrollToBottom();
        }

        function removePausePrompt() {
            const existing = document.getElementById('pause-widget');
            if (existing) existing.remove();
        }

        // ── Clarify Interview Widget ──
        function showClarifyForm(data) {
            if (!currentAssistantDiv) startAssistantMessage();

            const widget = document.createElement('div');
            widget.className = 'interactive-widget clarify-widget';

            // Header
            const header = document.createElement('div');
            header.className = 'widget-header';
            header.textContent = 'Clarification Needed';
            widget.appendChild(header);

            // Body
            const body = document.createElement('div');
            body.className = 'widget-body';

            // Context
            if (data.context) {
                const ctx = document.createElement('div');
                ctx.className = 'context-text';
                ctx.textContent = data.context;
                body.appendChild(ctx);
            }

            // Questions
            const formData = {};  // question_id -> value (string or string[])
            const questions = data.questions || [];
            for (const q of questions) {
                const group = document.createElement('div');
                group.className = 'question-group';

                const label = document.createElement('div');
                label.className = 'question-label';
                label.textContent = q.question || q.label || '';
                group.appendChild(label);

                const qId = q.id || q.label || ('q' + questions.indexOf(q));
                const isMulti = q.multi_select === true || q.type === 'multi_choice';

                if (q.options && q.options.length > 0) {
                    if (isMulti) {
                        // Checkboxes for multi-select questions
                        formData[qId] = [];
                        for (const opt of q.options) {
                            const row = document.createElement('div');
                            row.className = 'option-row';
                            const checkbox = document.createElement('input');
                            checkbox.type = 'checkbox';
                            checkbox.value = typeof opt === 'string' ? opt : (opt.id || opt.label || '');
                            checkbox.addEventListener('change', () => {
                                if (checkbox.checked) {
                                    formData[qId].push(checkbox.value);
                                } else {
                                    formData[qId] = formData[qId].filter(v => v !== checkbox.value);
                                }
                            });
                            row.appendChild(checkbox);
                            const optLabel = document.createElement('label');
                            optLabel.textContent = typeof opt === 'string' ? opt : (opt.label || opt.id || '');
                            row.appendChild(optLabel);
                            group.appendChild(row);
                        }
                    } else {
                        // Radio buttons for single-choice questions
                        formData[qId] = '';
                        for (const opt of q.options) {
                            const row = document.createElement('div');
                            row.className = 'option-row';
                            const radio = document.createElement('input');
                            radio.type = 'radio';
                            radio.name = 'clarify-' + qId;
                            radio.value = typeof opt === 'string' ? opt : (opt.id || opt.label || '');
                            radio.addEventListener('change', () => {
                                formData[qId] = radio.value;
                            });
                            row.appendChild(radio);
                            const optLabel = document.createElement('label');
                            optLabel.textContent = typeof opt === 'string' ? opt : (opt.label || opt.id || '');
                            row.appendChild(optLabel);
                            group.appendChild(row);
                        }
                    }

                    // "Other" custom input for choice questions
                    const customRow = document.createElement('div');
                    customRow.className = 'option-row';
                    customRow.style.marginTop = '4px';
                    const customInput = document.createElement('input');
                    customInput.type = 'text';
                    customInput.placeholder = 'Other (custom answer)...';
                    customInput.style.cssText = 'flex:1;background:var(--vscode-input-background);color:var(--vscode-input-foreground);border:1px solid var(--vscode-input-border);border-radius:2px;padding:3px 6px;font-size:12px;font-family:var(--vscode-font-family);';
                    customInput.addEventListener('input', () => {
                        if (customInput.value.trim()) {
                            // For multi-select, append custom value
                            if (isMulti) {
                                // Remove previous custom entry if any, then add new one
                                formData[qId] = formData[qId].filter(v => v !== customInput.dataset.prevCustom);
                                formData[qId].push(customInput.value.trim());
                                customInput.dataset.prevCustom = customInput.value.trim();
                            } else {
                                // For single-select, custom overrides radio
                                formData[qId] = customInput.value.trim();
                                // Uncheck all radios
                                group.querySelectorAll('input[type="radio"]').forEach(r => r.checked = false);
                            }
                        }
                    });
                    customRow.appendChild(customInput);
                    group.appendChild(customRow);
                } else {
                    // Textarea for open-ended questions (no options)
                    formData[qId] = '';
                    const textarea = document.createElement('textarea');
                    textarea.placeholder = 'Your answer...';
                    textarea.addEventListener('input', () => {
                        formData[qId] = textarea.value;
                    });
                    group.appendChild(textarea);
                }

                body.appendChild(group);
            }

            widget.appendChild(body);

            // Actions
            const actions = document.createElement('div');
            actions.className = 'widget-actions';

            const submitBtn = document.createElement('button');
            submitBtn.className = 'btn-primary';
            submitBtn.textContent = 'Submit';
            submitBtn.addEventListener('click', () => {
                vscode.postMessage({
                    type: 'clarifyResult',
                    callId: data.call_id,
                    submitted: true,
                    responses: formData,
                });
                // Replace widget with confirmation
                widget.innerHTML = '<div class="widget-body" style="font-size:12px;color:var(--vscode-descriptionForeground);">[Clarification submitted]</div>';
            });
            actions.appendChild(submitBtn);

            const cancelBtn = document.createElement('button');
            cancelBtn.className = 'btn-secondary';
            cancelBtn.textContent = 'Cancel';
            cancelBtn.addEventListener('click', () => {
                vscode.postMessage({
                    type: 'clarifyResult',
                    callId: data.call_id,
                    submitted: false,
                    responses: null,
                });
                widget.innerHTML = '<div class="widget-body" style="font-size:12px;color:var(--vscode-descriptionForeground);">[Clarification cancelled]</div>';
            });
            actions.appendChild(cancelBtn);

            widget.appendChild(actions);

            currentAssistantDiv.appendChild(widget);
            scrollToBottom();
        }

        // ── Plan Approval Widget ──
        function showPlanApproval(data) {
            if (!currentAssistantDiv) startAssistantMessage();

            const widget = document.createElement('div');
            widget.className = 'interactive-widget plan-widget';

            // Header
            const header = document.createElement('div');
            header.className = 'widget-header';
            const isDirector = data.event === 'director_plan_submitted';
            header.textContent = isDirector ? 'Director Plan Approval' : 'Plan Approval';
            widget.appendChild(header);

            // Body
            const body = document.createElement('div');
            body.className = 'widget-body';

            // Render plan as markdown
            const planContent = document.createElement('div');
            planContent.className = 'plan-content';
            try {
                planContent.innerHTML = (typeof marked !== 'undefined')
                    ? marked.parse(data.excerpt || '')
                    : escapeHtml(data.excerpt || '');
            } catch (e) {
                planContent.textContent = data.excerpt || '';
            }
            body.appendChild(planContent);

            widget.appendChild(body);

            // Truncation note
            if (data.truncated) {
                const note = document.createElement('div');
                note.className = 'truncation-note';
                note.textContent = 'Plan was truncated. Full plan saved to: ' + (data.plan_path || 'plan file');
                widget.appendChild(note);
            }

            // Actions
            const actions = document.createElement('div');
            actions.className = 'widget-actions';

            const approveBtn = document.createElement('button');
            approveBtn.className = 'btn-primary';
            approveBtn.textContent = 'Approve';
            approveBtn.addEventListener('click', () => {
                vscode.postMessage({
                    type: 'planApprovalResult',
                    planHash: data.plan_hash,
                    approved: true,
                    autoAcceptEdits: false,
                });
                widget.innerHTML = '<div class="widget-body" style="font-size:12px;color:var(--vscode-testing-iconPassed);">[Plan approved]</div>';
            });
            actions.appendChild(approveBtn);

            const autoBtn = document.createElement('button');
            autoBtn.className = 'btn-primary';
            autoBtn.textContent = 'Approve + Auto-accept Edits';
            autoBtn.style.fontSize = '11px';
            autoBtn.addEventListener('click', () => {
                vscode.postMessage({
                    type: 'planApprovalResult',
                    planHash: data.plan_hash,
                    approved: true,
                    autoAcceptEdits: true,
                });
                widget.innerHTML = '<div class="widget-body" style="font-size:12px;color:var(--vscode-testing-iconPassed);">[Plan approved (auto-accept edits)]</div>';
            });
            actions.appendChild(autoBtn);

            const rejectBtn = document.createElement('button');
            rejectBtn.className = 'btn-danger';
            rejectBtn.textContent = 'Reject';
            rejectBtn.addEventListener('click', () => {
                const feedback = feedbackArea.value.trim() || null;
                vscode.postMessage({
                    type: 'planApprovalResult',
                    planHash: data.plan_hash,
                    approved: false,
                    feedback: feedback,
                });
                widget.innerHTML = '<div class="widget-body" style="font-size:12px;color:var(--vscode-testing-iconFailed);">[Plan rejected]</div>';
            });
            actions.appendChild(rejectBtn);

            widget.appendChild(actions);

            // Feedback textarea (always visible, sent with Reject)
            const feedbackWrap = document.createElement('div');
            feedbackWrap.style.cssText = 'padding:6px 10px;';
            const feedbackArea = document.createElement('textarea');
            feedbackArea.placeholder = 'Feedback for the agent (sent with Reject)...';
            feedbackArea.style.cssText = 'width:100%;min-height:36px;max-height:80px;resize:vertical;background:var(--vscode-input-background);color:var(--vscode-input-foreground);border:1px solid var(--vscode-input-border);border-radius:2px;padding:4px 6px;font-family:var(--vscode-font-family);font-size:var(--vscode-font-size);';
            feedbackWrap.appendChild(feedbackArea);
            widget.appendChild(feedbackWrap);

            currentAssistantDiv.appendChild(widget);
            scrollToBottom();
        }

        // ── Main message handler ──
        window.addEventListener('message', (event) => {
            const msg = event.data;

            if (msg.type === 'connectionStatus') {
                connectionStatus.textContent = msg.status === 'connected' ? 'Connected' : 'Disconnected';
                connectionStatus.className = msg.status === 'connected' ? 'connected' : 'disconnected';
            }

            else if (msg.type === 'sessionInfo') {
                // If session ID changed, clear the chat UI (new session)
                if (currentSessionId && msg.sessionId !== currentSessionId) {
                    chatHistory.innerHTML = '';
                    currentAssistantDiv = null;
                    currentContentDiv = null;
                    currentCodeElement = null;
                    currentThinkingBlock = null;
                    markdownBuffer = '';
                    isStreaming = false;
                    sendBtn.disabled = false;
                    sendBtn.textContent = 'Send';
                    sendBtn.style.background = '';
                    sendBtn.onclick = sendMessage;
                    // Clear tool state caches
                    for (const key of Object.keys(toolCards)) delete toolCards[key];
                    for (const key of Object.keys(toolMeta)) delete toolMeta[key];
                    // Clear subagent state
                    for (const key of Object.keys(subagentContainers)) delete subagentContainers[key];
                    for (const key of Object.keys(subagentParents)) delete subagentParents[key];
                    // Clear todo panel
                    updateTodos([]);
                    // Reset context bar
                    contextBar.style.display = 'none';
                }
                currentSessionId = msg.sessionId;
                modelName.textContent = msg.model;
                updateModeDisplay(msg.permissionMode);
                updateAutoApproveDisplay(msg.autoApproveCategories);
            }

            else if (msg.type === 'serverMessage') {
                const payload = msg.payload;

                switch (payload.type) {
                    case 'stream_start':
                        isStreaming = true;
                        userScrolledUp = false;
                        sendBtn.disabled = false;
                        sendBtn.textContent = 'Stop';
                        sendBtn.style.background = 'var(--vscode-testing-iconFailed)';
                        sendBtn.onclick = () => vscode.postMessage({ type: 'interrupt' });
                        startAssistantMessage();
                        break;

                    case 'text_delta':
                        appendText(payload.content);
                        break;

                    case 'code_block_start':
                        startCodeBlock(payload.language || '');
                        break;

                    case 'code_block_delta':
                        appendCodeDelta(payload.content);
                        break;

                    case 'code_block_end':
                        endCodeBlock();
                        break;

                    case 'thinking_start':
                        startThinking();
                        break;

                    case 'thinking_delta':
                        appendThinking(payload.content || '');
                        break;

                    case 'thinking_end':
                        endThinking(payload.token_count);
                        break;

                    case 'stream_end':
                        // Final render of any buffered markdown
                        renderMarkdown();
                        if (payload.total_tokens || payload.duration_ms) {
                            showTurnStats(payload.total_tokens, payload.duration_ms);
                        }
                        isStreaming = false;
                        sendBtn.disabled = false;
                        sendBtn.textContent = 'Send';
                        sendBtn.style.background = '';
                        sendBtn.onclick = sendMessage;
                        currentAssistantDiv = null;
                        currentContentDiv = null;
                        currentCodeElement = null;
                        currentThinkingBlock = null;
                        markdownBuffer = '';
                        break;

                    case 'context_updated':
                        contextBar.style.display = 'block';
                        const pct = Math.round((payload.used / payload.limit) * 100);
                        contextText.textContent = pct + '% context used';
                        contextBarFill.style.width = pct + '%';
                        break;

                    case 'error':
                        const errDiv = document.createElement('div');
                        errDiv.className = 'message';
                        errDiv.style.color = 'var(--vscode-testing-iconFailed)';
                        errDiv.textContent = '[Error] ' + payload.user_message;
                        chatHistory.appendChild(errDiv);
                        scrollToBottom();
                        break;

                    case 'pause_prompt_start':
                        showPausePrompt(payload);
                        break;

                    case 'pause_prompt_end':
                        removePausePrompt();
                        break;

                    case 'store':
                        // Exhaustive handling of all store event types
                        // (see StoreEvent in types.ts — keep in sync)
                        if (payload.event === 'tool_state_updated' && payload.data) {
                            updateToolCard(payload.data, payload.subagent_id);
                        } else if (payload.event === 'message_added' && payload.data) {
                            if (payload.subagent_id) {
                                // Subagent text (assistant responses, initial task)
                                const saInfo = subagentContainers[payload.subagent_id];
                                const text = payload.data.content;
                                if (saInfo && text) {
                                    const role = payload.data.role || 'assistant';
                                    const msgId = 'sa-msg-' + (payload.data.uuid || '');
                                    let msgEl = saInfo.body.querySelector('[data-sa-msg="' + msgId + '"]');
                                    if (!msgEl) {
                                        msgEl = document.createElement('div');
                                        msgEl.className = 'subagent-text ' + role;
                                        msgEl.setAttribute('data-sa-msg', msgId);
                                        saInfo.body.appendChild(msgEl);
                                    }
                                    msgEl.textContent = text;
                                    scrollToBottom();
                                }
                            }
                            // Parent message_added: handled by stream events (text_delta etc.)
                        } else if (payload.event === 'message_updated' && payload.data) {
                            if (payload.subagent_id) {
                                const saInfo = subagentContainers[payload.subagent_id];
                                const text = payload.data.content;
                                if (saInfo && text) {
                                    const msgId = 'sa-msg-' + (payload.data.uuid || '');
                                    const msgEl = saInfo.body.querySelector('[data-sa-msg="' + msgId + '"]');
                                    if (msgEl) { msgEl.textContent = text; }
                                }
                            }
                        } else if (payload.event === 'message_finalized') {
                            // Stream finalization — no action needed (stream_end handles UI)
                        } else {
                            console.warn('[ClarAIty] Unhandled store event:', payload.event);
                        }
                        break;

                    case 'subagent':
                        if (payload.event === 'registered' && payload.data) {
                            const d = payload.data;
                            subagentParents[d.subagent_id] = d.parent_tool_call_id;

                            const parentCard = toolCards[d.parent_tool_call_id];
                            if (parentCard) {
                                // Merge subagent identity into the parent tool card header
                                const nameEl = parentCard.querySelector('.tool-name');
                                if (nameEl) {
                                    nameEl.textContent = d.subagent_name + (d.model_name ? ' (' + d.model_name + ')' : '');
                                }
                                const iconEl = parentCard.querySelector('.tool-icon');
                                if (iconEl) iconEl.textContent = 'SA';

                                // Collapsible body for child tool cards (no summary — header IS the label)
                                const details = document.createElement('details');
                                details.className = 'subagent-details';
                                details.open = true;

                                const body = document.createElement('div');
                                body.className = 'subagent-body';
                                details.appendChild(body);

                                parentCard.appendChild(details);
                                subagentContainers[d.subagent_id] = { details, body, summary: null, toolCount: 0 };
                            }
                        } else if (payload.event === 'unregistered' && payload.data) {
                            const info = subagentContainers[payload.data.subagent_id];
                            if (info) {
                                info.details.open = false;
                                // Update parent tool card header with final tool count
                                const parentId = subagentParents[payload.data.subagent_id];
                                const parentCard = parentId && toolCards[parentId];
                                if (parentCard) {
                                    const nameEl = parentCard.querySelector('.tool-name');
                                    if (nameEl) {
                                        const currentName = nameEl.textContent.replace(/ \| \d+ tools$/, '');
                                        nameEl.textContent = currentName + ' | ' + info.toolCount + ' tools';
                                    }
                                }
                            }
                            delete subagentContainers[payload.data.subagent_id];
                            delete subagentParents[payload.data.subagent_id];
                        }
                        break;

                    case 'interactive':
                        if (payload.event === 'clarify_request' && payload.data) {
                            showClarifyForm(payload.data);
                        } else if (
                            (payload.event === 'plan_submitted' || payload.event === 'director_plan_submitted')
                            && payload.data
                        ) {
                            showPlanApproval({ ...payload.data, event: payload.event });
                        } else if (payload.event === 'permission_mode_changed' && payload.data) {
                            updateModeDisplay(payload.data.new_mode);
                        }
                        break;

                    case 'todos_updated':
                        updateTodos(payload.todos);
                        break;

                    case 'config_loaded':
                        populateConfigForm(payload);
                        break;

                    case 'models_list':
                        populateModelList(payload);
                        break;

                    case 'config_saved':
                        handleConfigSaved(payload);
                        break;

                    case 'auto_approve_changed':
                        updateAutoApproveDisplay(payload.categories);
                        break;
                }
            }
        });

        // ── Config panel ──
        const configGear = document.getElementById('config-gear');
        const configPanel = document.getElementById('config-panel');
        const configClose = document.getElementById('config-close');
        const cfgNotification = document.getElementById('cfg-notification');
        const cfgBackend = document.getElementById('cfg-backend');
        const cfgBaseUrl = document.getElementById('cfg-base-url');
        const cfgApiKey = document.getElementById('cfg-api-key');
        const cfgKeyIndicator = document.getElementById('cfg-key-indicator');
        const cfgModel = document.getElementById('cfg-model');
        const cfgFetchBtn = document.getElementById('cfg-fetch-btn');
        const cfgFetchStatus = document.getElementById('cfg-fetch-status');
        const cfgModelList = document.getElementById('cfg-model-list');
        const cfgTemperature = document.getElementById('cfg-temperature');
        const cfgMaxTokens = document.getElementById('cfg-max-tokens');
        const cfgContextWindow = document.getElementById('cfg-context-window');
        const cfgThinkingBudget = document.getElementById('cfg-thinking-budget');
        const cfgSubagentsToggle = document.getElementById('cfg-subagents-toggle');
        const cfgSubagentsSection = document.getElementById('cfg-subagents-section');
        const cfgSameModel = document.getElementById('cfg-same-model');
        const cfgSubagentInputs = document.getElementById('cfg-subagent-inputs');
        const cfgSaveBtn = document.getElementById('cfg-save-btn');
        const cfgCancelBtn = document.getElementById('cfg-cancel-btn');

        let cfgSubagentNames = [];

        function toggleConfigPanel() {
            const isVisible = configPanel.classList.contains('visible');
            if (isVisible) {
                configPanel.classList.remove('visible');
            } else {
                configPanel.classList.add('visible');
                cfgNotification.className = '';
                cfgNotification.textContent = '';
                vscode.postMessage({ type: 'getConfig' });
            }
        }

        configGear.addEventListener('click', toggleConfigPanel);
        configClose.addEventListener('click', () => configPanel.classList.remove('visible'));

        // Backend change -> auto-suggest URL
        cfgBackend.addEventListener('change', () => {
            const val = cfgBackend.value;
            if (val === 'ollama') cfgBaseUrl.value = 'http://localhost:11434';
            else if (val === 'anthropic') cfgBaseUrl.value = '';
            else cfgBaseUrl.value = cfgBaseUrl.value || 'http://localhost:8000/v1';
        });

        // Fetch models
        cfgFetchBtn.addEventListener('click', () => {
            cfgFetchStatus.textContent = 'Fetching...';
            cfgModelList.innerHTML = '';
            cfgModelList.classList.remove('visible');
            vscode.postMessage({
                type: 'listModels',
                backend: cfgBackend.value,
                base_url: cfgBaseUrl.value,
                api_key: cfgApiKey.value,
            });
        });

        // Subagent toggle
        cfgSubagentsToggle.addEventListener('click', () => {
            const isVisible = cfgSubagentsSection.classList.contains('visible');
            cfgSubagentsSection.classList.toggle('visible');
            cfgSubagentsToggle.textContent = isVisible ? '+ Subagent Models' : '- Subagent Models';
        });

        // Same model checkbox
        cfgSameModel.addEventListener('change', () => {
            if (cfgSameModel.checked) {
                const mainModel = cfgModel.value;
                const inputs = cfgSubagentInputs.querySelectorAll('input');
                inputs.forEach(inp => { inp.value = mainModel; });
            }
        });

        // Save
        cfgSaveBtn.addEventListener('click', () => {
            const subagentModels = {};
            for (const name of cfgSubagentNames) {
                const inp = document.getElementById('cfg-sa-' + name);
                if (inp && inp.value.trim()) {
                    subagentModels[name] = inp.value.trim();
                }
            }

            const configData = {
                backend_type: cfgBackend.value,
                base_url: cfgBaseUrl.value,
                api_key: cfgApiKey.value,
                model: cfgModel.value,
                temperature: cfgTemperature.value,
                max_tokens: cfgMaxTokens.value,
                context_window: cfgContextWindow.value,
                thinking_budget: cfgThinkingBudget.value || null,
                subagent_models: subagentModels,
            };

            vscode.postMessage({ type: 'saveConfig', config: configData });
        });

        // Cancel
        cfgCancelBtn.addEventListener('click', () => {
            configPanel.classList.remove('visible');
        });

        function populateConfigForm(data) {
            const cfg = data.config || {};
            cfgBackend.value = cfg.backend_type || 'openai';
            cfgBaseUrl.value = cfg.base_url || '';
            cfgApiKey.value = cfg.api_key || '';
            cfgKeyIndicator.textContent = cfg.has_api_key ? '(key stored)' : '(not set)';
            cfgModel.value = cfg.model || '';
            cfgTemperature.value = cfg.temperature != null ? cfg.temperature : 0.2;
            cfgMaxTokens.value = cfg.max_tokens != null ? cfg.max_tokens : 16384;
            cfgContextWindow.value = cfg.context_window != null ? cfg.context_window : 131072;
            cfgThinkingBudget.value = cfg.thinking_budget != null ? cfg.thinking_budget : '';

            // Build subagent inputs
            cfgSubagentNames = data.subagent_names || [];
            cfgSubagentInputs.innerHTML = '';
            const saModels = cfg.subagent_models || {};
            for (const name of cfgSubagentNames) {
                const row = document.createElement('div');
                row.className = 'cfg-subagent-row';
                const lbl = document.createElement('label');
                lbl.textContent = name;
                row.appendChild(lbl);
                const inp = document.createElement('input');
                inp.type = 'text';
                inp.id = 'cfg-sa-' + name;
                inp.placeholder = '(inherit from main)';
                inp.value = saModels[name] || '';
                row.appendChild(inp);
                cfgSubagentInputs.appendChild(row);
            }

            // Reset model list
            cfgModelList.innerHTML = '';
            cfgModelList.classList.remove('visible');
            cfgFetchStatus.textContent = '';
        }

        function populateModelList(data) {
            cfgModelList.innerHTML = '';
            if (data.error) {
                cfgFetchStatus.textContent = 'Error: ' + data.error;
                return;
            }
            const models = data.models || [];
            if (models.length === 0) {
                cfgFetchStatus.textContent = 'No models found';
                return;
            }
            cfgFetchStatus.textContent = models.length + ' model(s)';
            cfgModelList.classList.add('visible');
            for (const m of models) {
                const opt = document.createElement('div');
                opt.className = 'model-option';
                opt.textContent = m;
                opt.addEventListener('click', () => {
                    cfgModel.value = m;
                    // Highlight selected
                    cfgModelList.querySelectorAll('.model-option').forEach(o => o.classList.remove('selected'));
                    opt.classList.add('selected');
                });
                cfgModelList.appendChild(opt);
            }
        }

        function handleConfigSaved(data) {
            cfgNotification.textContent = data.message || '';
            cfgNotification.className = data.success ? 'success' : 'error';
            if (data.success) {
                setTimeout(() => {
                    configPanel.classList.remove('visible');
                    cfgNotification.className = '';
                    cfgNotification.textContent = '';
                }, 3000);
            }
        }

        // Signal ready
        vscode.postMessage({ type: 'ready' });
    </script>
</body>
</html>`;
    }
}
