/**
 * WebView sidebar provider for the ClarAIty chat panel.
 *
 * Responsibilities:
 * - Provide WebView HTML that loads the React app
 * - Bridge messages between WebSocket server and WebView
 * - Trigger VS Code native actions (diff editor, file open)
 */

import * as vscode from 'vscode';
import * as path from 'path';
import * as fs from 'fs';
import { StdioConnection } from './stdio-connection';
import { ServerMessage, ExtensionMessage, ClientMessage, WebViewMessage, FileAttachment, ImageAttachment } from './types';

/** Connection type accepted by the sidebar (WebSocket or stdio). */
type AnyConnection = StdioConnection;


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

    /** Clear all stored diffs (e.g., on new session). */
    clearAll(): void {
        this.content.clear();
    }

    dispose(): void {
        this.content.clear();
        this._onDidChange.dispose();
    }
}


/**
 * Executes agent commands via child_process.exec with real exit code capture.
 *
 * Uses child_process instead of VS Code Terminal API because Terminal
 * cannot reliably capture exit codes or output programmatically.
 *
 * Commands are queued and executed sequentially. Each command runs
 * with stdin=DEVNULL to prevent stdin inheritance deadlocks on Windows.
 */
class CommandExecutor {
    private queue: Array<{
        taskId: string;
        command: string;
        workingDir?: string;
        timeout?: number;
    }> = [];
    private isRunning = false;
    private onResult: (taskId: string, exitCode: number, output: string, error: string) => void;

    constructor(
        onResult: (taskId: string, exitCode: number, output: string, error: string) => void,
    ) {
        this.onResult = onResult;
    }

    async queueCommand(
        taskId: string,
        command: string,
        workingDir?: string,
        timeout?: number,
    ): Promise<void> {
        this.queue.push({ taskId, command, workingDir, timeout });
        if (!this.isRunning) {
            await this.processQueue();
        }
    }

    private async processQueue(): Promise<void> {
        this.isRunning = true;
        while (this.queue.length > 0) {
            const cmd = this.queue.shift()!;
            await this.executeCommand(cmd.taskId, cmd.command, cmd.workingDir, cmd.timeout);
        }
        this.isRunning = false;
    }

    private executeCommand(
        taskId: string,
        command: string,
        workingDir?: string,
        timeout?: number,
    ): Promise<void> {
        const { exec } = require('child_process') as typeof import('child_process');
        const timeoutMs = (timeout ?? 120) * 1000;
        // Cap output at 2MB to prevent memory exhaustion
        const maxBuffer = 2 * 1024 * 1024;

        // Choose shell based on platform (array form not available with exec,
        // but shell is required for piped commands and redirects)
        const shell = process.platform === 'win32' ? 'powershell.exe' : '/bin/bash';

        return new Promise<void>((resolve) => {
            const child = exec(
                command,
                {
                    cwd: workingDir || undefined,
                    timeout: timeoutMs,
                    maxBuffer,
                    shell,
                    windowsHide: true,
                },
                (error, stdout, stderr) => {
                    const exitCode = error ? (error as any).code ?? 1 : 0;
                    const output = (stdout || '') + (stderr ? '\n[stderr]\n' + stderr : '');
                    this.onResult(taskId, exitCode, output, error ? error.message : '');
                    resolve();
                },
            );
            // Prevent stdin inheritance deadlock on Windows (CLAUDE.md gotcha #8)
            child.stdin?.end();
        });
    }

    dispose(): void {
        this.queue = [];
    }
}


export class ClarAItySidebarProvider implements vscode.WebviewViewProvider {
    private view?: vscode.WebviewView;
    private diffProvider: DiffContentProvider;
    private diffProviderRegistration: vscode.Disposable;


    private commandExecutor: CommandExecutor;
    private secrets: vscode.SecretStorage | null = null;

    constructor(
        private extensionUri: vscode.Uri,
        private connection: AnyConnection | null,
        private log?: vscode.OutputChannel,
    ) {
        // Register diff content provider for claraity-diff: URI scheme
        this.diffProvider = new DiffContentProvider();
        this.diffProviderRegistration = vscode.workspace.registerTextDocumentContentProvider(
            'claraity-diff',
            this.diffProvider,
        );

        // Initialize terminal queue for run_command execution
        this.commandExecutor = new CommandExecutor((taskId, exitCode, output, error) => {
            // Send result back to agent
            this.connection?.send({
                type: 'terminal_result',
                task_id: taskId,
                exit_code: exitCode,
                output: output,
                error: error,
            } as ClientMessage);
        });

        // Wire connection events if available (deferred in stdio mode)
        if (this.connection) {
            this.wireConnectionEvents(this.connection);
        }
    }

    /**
     * Set or replace the connection (used for stdio mode where connection
     * is created asynchronously after the sidebar provider).
     */
    setConnection(conn: AnyConnection): void {
        this.connection = conn;
        this.wireConnectionEvents(conn);
    }

    /**
     * Set the SecretStorage instance for persisting API keys.
     * Called from extension.ts with context.secrets.
     */
    setSecrets(secrets: vscode.SecretStorage): void {
        this.secrets = secrets;
    }

    private wireConnectionEvents(conn: AnyConnection): void {
        // Forward server messages to webview
        conn.onMessage((msg: ServerMessage) => {
            this.handleServerMessage(msg);
        });

        // Forward connection status to webview
        conn.onConnected(() => {
            this.postToWebview({ type: 'connectionStatus', status: 'connected' });
        });

        conn.onDisconnected(() => {
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
        // Augment config_loaded: mark has_api_key / has_search_key if SecretStorage has keys
        if (msg.type === 'config_loaded' && this.secrets) {
            Promise.all([
                this.secrets.get('claraity.apiKey'),
                this.secrets.get('claraity.tavilyKey'),
            ]).then(([apiKey, tavilyKey]) => {
                const raw = msg as Record<string, unknown>;
                const config = (raw.config ?? {}) as Record<string, unknown>;
                if (apiKey) { config.has_api_key = true; }
                if (tavilyKey) { config.has_search_key = true; }
                const augmented = { ...raw, config } as unknown as ServerMessage;
                this.postToWebview({ type: 'serverMessage', payload: augmented });
            });
            // Don't forward yet — the async handler above will do it
        } else {
            // Forward to webview for rendering
            this.postToWebview({ type: 'serverMessage', payload: msg });
        }

        // Extract session info for status bar etc.
        if (msg.type === 'session_info') {
            this.diffProvider.clearAll(); // Free memory from previous session's diffs
            this.postToWebview({
                type: 'sessionInfo',
                sessionId: msg.session_id,
                model: msg.model_name,
                permissionMode: msg.permission_mode,
                autoApproveCategories: msg.auto_approve_categories,
                limits: msg.limits,
            });
        }

        // Route session history messages directly to webview
        if (msg.type === 'sessions_list') {
            this.postToWebview({ type: 'sessionsList', sessions: msg.sessions });
        }
        if (msg.type === 'session_history') {
            this.postToWebview({ type: 'sessionHistory', messages: msg.messages });
        }
        if (msg.type === 'session_deleted') {
            this.postToWebview({ type: 'serverMessage', payload: msg });
        }
        if (msg.type === 'trace_enabled') {
            this.postToWebview({ type: 'traceEnabled', enabled: msg.enabled });
        }

        if (msg.type === 'tool_list') {
            this.postToWebview({ type: 'toolList', tools: msg.tools });
        }

        // Handle VS Code terminal execution
        if (msg.type === 'execute_in_terminal') {
            this.commandExecutor.queueCommand(msg.task_id, msg.command, msg.working_dir, msg.timeout);
        }

        // Prompt enrichment — forward streaming deltas and completion to webview
        if (msg.type === 'enrichment_delta') {
            this.postToWebview({ type: 'enrichmentDelta', delta: msg.delta });
        }
        if (msg.type === 'enrichment_complete') {
            this.postToWebview({ type: 'enrichmentComplete', original: msg.original, enriched: msg.enriched });
        }
        if (msg.type === 'enrichment_error') {
            this.postToWebview({ type: 'enrichmentError', message: msg.message });
        }

        // Stop reconnecting on non-recoverable errors
        if (msg.type === 'error' && msg.recoverable === false) {
            this.connection?.disconnect();
        }
    }

    /**
     * WebView -> Extension -> Server message routing.
     */
    private async handleWebviewMessage(msg: WebViewMessage): Promise<void> {
        switch (msg.type) {
            case 'chatMessage':
                this.sendChatWithAttachments(msg.content, msg.attachments, msg.images, msg.systemContext);
                break;

            case 'searchFiles':
                this.searchWorkspaceFiles(msg.query);
                break;

            case 'approvalResult':
                this.connection?.send({
                    type: 'approval_result',
                    call_id: msg.callId,
                    approved: msg.approved,
                    auto_approve_future: msg.autoApproveFuture ?? false,
                    feedback: msg.feedback ?? null,
                });
                // Free diff content memory after approval/rejection
                this.diffProvider.clear(msg.callId);
                break;

            case 'interrupt':
                this.connection?.send({ type: 'interrupt' });
                break;

            case 'ready':
                // WebView finished loading — send current connection state
                if (this.connection?.isConnected) {
                    this.postToWebview({ type: 'connectionStatus', status: 'connected' });
                }
                break;

            case 'copyToClipboard':
                vscode.env.clipboard.writeText(msg.text);
                break;

            case 'pauseResult':
                this.connection?.send({
                    type: 'pause_result',
                    continue_work: msg.continueWork,
                    feedback: msg.feedback ?? null,
                });
                break;

            case 'showDiff':
                this.openDiffEditor(msg.callId, msg.toolName, msg.arguments);
                break;

            case 'clarifyResult':
                this.connection?.send({
                    type: 'clarify_result',
                    call_id: msg.callId,
                    submitted: msg.submitted,
                    responses: msg.responses,
                    chat_instead: false,
                    chat_message: null,
                });
                break;

            case 'planApprovalResult':
                this.connection?.send({
                    type: 'plan_approval_result',
                    plan_hash: msg.planHash,
                    approved: msg.approved,
                    auto_accept_edits: msg.autoAcceptEdits ?? false,
                    feedback: msg.feedback ?? null,
                });
                break;

            case 'setMode':
                this.connection?.send({ type: 'set_mode', mode: msg.mode });
                break;

            case 'getConfig':
                this.connection?.send({ type: 'get_config' });
                break;

            case 'saveConfig': {
                const config = msg.config ?? {};

                // Intercept API key: store in VS Code SecretStorage
                // (industry standard — never forwarded to agent config file)
                const apiKey = config.api_key;
                if (apiKey && this.secrets) {
                    this.secrets.store('claraity.apiKey', apiKey).then(() => {
                        this.log?.appendLine('[ClarAIty] API key saved to SecretStorage');
                        // Update StdioConnection so next spawn uses the new key
                        if (this.connection) {
                            this.connection.setApiKey(apiKey);
                        }
                    });
                }

                // Intercept search API key: store in SecretStorage, inject at next spawn
                const searchKey = config.search_key;
                if (searchKey && this.secrets) {
                    this.secrets.store('claraity.tavilyKey', searchKey).then(() => {
                        this.log?.appendLine('[ClarAIty] Tavily key saved to SecretStorage');
                        if (this.connection) {
                            this.connection.setTavilyKey(searchKey);
                        }
                    });
                }

                // Forward config to agent — include api_key so the running process
                // can hot-swap backends without a restart.  The Python side uses it
                // for reconfigure_llm() but never persists it to config.yaml.
                // Strip search_key only (injected via env var at spawn).
                const { search_key: _sStripped, ...configWithoutSearchKey } = config;
                this.connection?.send({ type: 'save_config', config: configWithoutSearchKey } as ClientMessage);
                break;
            }

            case 'listModels': {
                // Resolve API key: use stored key from SecretStorage when sentinel is sent
                let resolvedKey = msg.api_key;
                if (resolvedKey === '__use_stored__' && this.secrets) {
                    resolvedKey = await this.secrets.get('claraity.apiKey') ?? '';
                }
                this.connection?.send({
                    type: 'list_models',
                    backend: msg.backend,
                    base_url: msg.base_url,
                    api_key: resolvedKey,
                } as ClientMessage);
                break;
            }

            case 'setAutoApprove':
                this.connection?.send({ type: 'set_auto_approve', categories: msg.categories } as ClientMessage);
                break;

            case 'getAutoApprove':
                this.connection?.send({ type: 'get_auto_approve' } as ClientMessage);
                break;

            case 'enrichPrompt':
                this.connection?.send({ type: 'enrich_prompt', content: msg.content, history: msg.history } as ClientMessage);
                break;

            case 'cancelBackgroundTask':
                this.connection?.send({ type: 'cancel_background_task', task_id: msg.taskId } as ClientMessage);
                break;

            case 'disconnectServer':
                this.connection?.disconnect();
                break;

            case 'reconnectServer':
                this.connection?.restart();
                break;

            case 'getLimits':
                this.connection?.send({ type: 'get_limits' } as ClientMessage);
                break;

            case 'saveLimits':
                this.connection?.send({ type: 'save_limits', limits: msg.limits } as ClientMessage);
                break;

            case 'newSession':
                this.connection?.send({ type: 'new_session' });
                break;

            case 'listSessions':
                this.connection?.send({ type: 'list_sessions' } as ClientMessage);
                break;

            case 'resumeSession':
                this.connection?.send({ type: 'resume_session', session_id: msg.sessionId } as ClientMessage);
                break;

            case 'deleteSession':
                this.connection?.send({ type: 'delete_session', session_id: msg.sessionId } as ClientMessage);
                break;

            case 'undoTurn':
                vscode.commands.executeCommand('claraity.undoTurn', msg.turnId);
                break;

            case 'deleteTurn':
                this.connection?.send({ type: 'delete_turn', anchor_uuid: msg.anchorUuid } as ClientMessage);
                break;

            case 'restoreTurn':
                this.connection?.send({ type: 'restore_turn', anchor_uuid: msg.anchorUuid } as ClientMessage);
                break;

            case 'pickFile':
                this.pickFileFromDisk();
                break;

            case 'openFile':
                if (msg.path) {
                    const workspaceRoot = vscode.workspace.workspaceFolders?.[0]?.uri.fsPath;
                    // Resolve relative paths against workspace root
                    const resolvedPath = workspaceRoot && !path.isAbsolute(msg.path)
                        ? path.join(workspaceRoot, msg.path)
                        : path.resolve(msg.path);
                    if (workspaceRoot && !resolvedPath.startsWith(path.resolve(workspaceRoot) + path.sep)) {
                        vscode.window.showWarningMessage('Can only open files within the workspace.');
                        break;
                    }
                    const uri = vscode.Uri.file(resolvedPath);
                    vscode.window.showTextDocument(uri, { preview: true }).then(undefined, () => {
                        vscode.window.showWarningMessage(`Could not open file: ${msg.path}`);
                    });
                }
                break;

            case 'getJiraProfiles':
                this.connection?.send({ type: 'get_jira_profiles' } as ClientMessage);
                break;

            case 'saveJiraConfig':
                this.connection?.send({
                    type: 'save_jira_config',
                    profile: msg.profile,
                    jira_url: msg.jira_url,
                    username: msg.username,
                    api_token: msg.api_token,
                } as ClientMessage);
                break;

            case 'connectJira':
                this.connection?.send({ type: 'connect_jira', profile: msg.profile } as ClientMessage);
                break;

            case 'disconnectJira':
                this.connection?.send({ type: 'disconnect_jira' } as ClientMessage);
                break;

            // ── MCP ──
            case 'getMcpServers':
                this.connection?.send({ type: 'get_mcp_servers' });
                break;

            case 'mcpOpenConfig': {
                const scope = (msg as { scope?: string }).scope ?? 'project';
                let configPath: string;
                if (scope === 'global') {
                    const homeDir = require('os').homedir();
                    configPath = path.join(homeDir, '.claraity', 'mcp_settings.json');
                } else {
                    const workspaceRoot = vscode.workspace.workspaceFolders?.[0]?.uri.fsPath;
                    if (!workspaceRoot) break;
                    configPath = path.join(workspaceRoot, '.claraity', 'mcp_settings.json');
                }
                const uri = vscode.Uri.file(configPath);
                const fs = require('fs') as typeof import('fs');
                if (!fs.existsSync(configPath)) {
                    const dir = path.dirname(configPath);
                    if (!fs.existsSync(dir)) { fs.mkdirSync(dir, { recursive: true }); }
                    fs.writeFileSync(configPath, JSON.stringify({ mcpServers: {} }, null, 2) + '\n', 'utf-8');
                }
                vscode.window.showTextDocument(uri, { preview: false });
                break;
            }

            case 'mcpReload':
                this.connection?.send({ type: 'mcp_reload' });
                break;

            case 'mcpMarketplaceSearch':
                this.connection?.send({
                    type: 'mcp_marketplace_search',
                    query: msg.query,
                    page: msg.page,
                });
                break;

            case 'mcpInstall':
                this.connection?.send({
                    type: 'mcp_install',
                    server_id: msg.serverId,
                    name: msg.name,
                    scope: msg.scope ?? 'project',
                });
                break;

            case 'mcpUninstall':
                this.connection?.send({
                    type: 'mcp_uninstall',
                    server_name: msg.serverName,
                });
                break;

            case 'mcpToggleServer':
                this.connection?.send({
                    type: 'mcp_toggle_server',
                    server_name: msg.serverName,
                    enabled: msg.enabled,
                });
                break;

            case 'mcpSaveTools':
                this.connection?.send({
                    type: 'mcp_save_tools',
                    server_name: msg.serverName,
                    tools: msg.tools,
                });
                break;

            case 'mcpReconnect':
                this.connection?.send({
                    type: 'mcp_reconnect',
                    server_name: msg.serverName,
                });
                break;

            case 'mcpOpenDocs':
                vscode.env.openExternal(vscode.Uri.parse(msg.url));
                break;

            // ── ClarAIty Knowledge & Beads ──
            case 'getBeads':
                this.connection?.send({ type: 'get_beads' });
                break;

            case 'getArchitecture':
                this.connection?.send({ type: 'get_architecture' });
                break;

            case 'getTrace': {
                // Read trace file directly from disk (no round-trip to Python server)
                const wsRoot = vscode.workspace.workspaceFolders?.[0]?.uri.fsPath;
                const sid = msg.sessionId;
                if (!wsRoot || !sid) {
                    this.postToWebview({ type: 'traceData', steps: [] });
                    break;
                }
                // Path traversal guard: ensure resolved path stays inside sessions dir
                const sessionsDir = path.join(wsRoot, '.claraity', 'sessions');
                const tracePath = path.join(sessionsDir, `${sid}.trace.jsonl`);
                const resolved = path.resolve(tracePath);
                if (!resolved.startsWith(path.resolve(sessionsDir) + path.sep) && resolved !== path.resolve(sessionsDir)) {
                    console.error('[ClarAIty] getTrace: path traversal blocked for sessionId:', sid);
                    this.postToWebview({ type: 'traceData', steps: [] });
                    break;
                }
                try {
                    if (fs.existsSync(tracePath)) {
                        const raw = fs.readFileSync(tracePath, 'utf-8');
                        const steps = raw.trim().split('\n')
                            .filter(Boolean)
                            .map((line: string) => JSON.parse(line));
                        // Inline subagent traces: scan for subagent_start events,
                        // read their trace files, and insert steps after the bookend.
                        const expanded = this.inlineSubagentTraces(steps, sessionsDir);
                        this.postToWebview({ type: 'traceData', steps: expanded });
                    } else {
                        this.postToWebview({ type: 'traceData', steps: [] });
                    }
                } catch (err) {
                    console.error('[ClarAIty] Failed to read trace file:', err);
                    this.postToWebview({ type: 'traceData', steps: [] });
                }
                break;
            }

            case 'clearTrace': {
                const wsRoot = vscode.workspace.workspaceFolders?.[0]?.uri.fsPath;
                const sid = msg.sessionId;
                if (!wsRoot || !sid) break;
                const sessionsDir = path.join(wsRoot, '.claraity', 'sessions');
                const tracePath = path.join(sessionsDir, `${sid}.trace.jsonl`);
                const resolved = path.resolve(tracePath);
                if (!resolved.startsWith(path.resolve(sessionsDir) + path.sep) && resolved !== path.resolve(sessionsDir)) break;
                const answer = await vscode.window.showWarningMessage(
                    'Clear trace data for this session? This cannot be undone.',
                    { modal: true },
                    'Clear'
                );
                if (answer === 'Clear') {
                    try { fs.unlinkSync(tracePath); } catch { /* ignore if already gone */ }
                    this.postToWebview({ type: 'traceData', steps: [] });
                }
                break;
            }

            case 'setTraceEnabled':
                this.connection?.send({ type: 'set_trace_enabled', enabled: msg.enabled });
                break;

            case 'getTraceEnabled':
                this.connection?.send({ type: 'get_trace_enabled' });
                break;

            case 'getToolList':
                this.connection?.send({ type: 'get_tool_list' });
                break;

            case 'approveKnowledge':
                this.connection?.send({
                    type: 'approve_knowledge',
                    approved_by: msg.approvedBy,
                    status: (msg as any).status,
                    comments: (msg as any).comments,
                } as ClientMessage);
                break;

            case 'exportKnowledge':
                this.exportKnowledgeToFile();
                break;

            case 'importKnowledge':
                this.importKnowledgeFromFile();
                break;

            // ── Subagent management ──
            case 'listSubagents':
                this.connection?.send({ type: 'list_subagents' });
                break;

            case 'saveSubagent':
                if (!this.connection) {
                    this.postToWebview({ type: 'serverMessage', payload: { type: 'subagent_saved', success: false, name: msg.name, message: 'Not connected to agent.' } });
                    break;
                }
                this.connection.send({
                    type: 'save_subagent',
                    name: msg.name,
                    description: msg.description,
                    system_prompt: msg.systemPrompt,
                    tools: msg.tools ?? null,
                    is_fork: msg.isFork ?? false,
                } as ClientMessage);
                break;

            case 'deleteSubagent':
                if (!this.connection) {
                    this.postToWebview({ type: 'serverMessage', payload: { type: 'subagent_deleted', success: false, name: msg.name, message: 'Not connected to agent.' } });
                    break;
                }
                this.connection.send({
                    type: 'delete_subagent',
                    name: msg.name,
                } as ClientMessage);
                break;

            case 'forkSubagent':
                this.connection?.send({
                    type: 'save_subagent',
                    name: msg.name,
                    description: msg.baseDescription,
                    system_prompt: msg.basePrompt,
                    tools: msg.baseTools ?? null,
                    is_fork: true,
                } as ClientMessage);
                break;

            case 'openSubagentFile': {
                const workspaceRoot = vscode.workspace.workspaceFolders?.[0]?.uri.fsPath;
                if (!workspaceRoot) {
                    vscode.window.showWarningMessage('No workspace folder open.');
                    break;
                }
                const agentFilePath = path.join(workspaceRoot, '.claraity', 'agents', `${msg.name}.md`);
                const fs = require('fs') as typeof import('fs');
                if (!fs.existsSync(agentFilePath)) {
                    vscode.window.showWarningMessage(
                        `No project-level config for '${msg.name}'. Fork it first to create an editable copy.`
                    );
                    break;
                }
                vscode.window.showTextDocument(vscode.Uri.file(agentFilePath), { preview: false });
                break;
            }

            case 'webviewError':
                this.log?.appendLine(`[ClarAIty] Webview error: ${msg.error}\n${msg.stack ?? ''}`);
                this.connection?.send({
                    type: 'webview_error',
                    error: msg.error,
                    stack: msg.stack,
                    component_stack: msg.componentStack,
                    session_id: msg.sessionId,
                } as ClientMessage);
                break;
        }
    }

    /** Binary file extensions that cannot be meaningfully read as text. */
    private static readonly BINARY_EXTENSIONS = new Set([
        '.docx', '.doc', '.xlsx', '.xls', '.pptx', '.ppt',
        '.pdf', '.zip', '.tar', '.gz', '.bz2', '.7z', '.rar',
        '.exe', '.dll', '.so', '.dylib', '.bin',
        '.png', '.jpg', '.jpeg', '.gif', '.bmp', '.ico', '.webp', '.tiff',
        '.mp3', '.mp4', '.avi', '.mov', '.wav', '.flac',
        '.pyc', '.pyo', '.class', '.o', '.obj',
        '.woff', '.woff2', '.ttf', '.eot',
        '.sqlite', '.db',
    ]);

    /**
     * Open native file picker and send the selected file back to the webview
     * as a FileAttachment (path + name). Rejects binary files.
     */
    private async pickFileFromDisk(): Promise<void> {
        const result = await vscode.window.showOpenDialog({
            canSelectMany: false,
            canSelectFolders: false,
            openLabel: 'Attach file',
        });
        if (!result || result.length === 0) return;

        const uri = result[0];
        const ext = path.extname(uri.fsPath).toLowerCase();
        if (ClarAItySidebarProvider.BINARY_EXTENSIONS.has(ext)) {
            vscode.window.showWarningMessage(
                `Cannot attach ${ext} files. Only text-based files are supported (code, config, logs, etc.).`
            );
            return;
        }

        const name = uri.path.split('/').pop() ?? uri.fsPath.split(/[\\/]/).pop() ?? 'file';
        this.postToWebview({
            type: 'fileSelected',
            path: uri.fsPath,
            name,
        });
    }

    /**
     * Show Save As dialog, then tell the backend to export the knowledge DB
     * to the chosen file path.
     */
    private async exportKnowledgeToFile(): Promise<void> {
        const wsRoot = vscode.workspace.workspaceFolders?.[0]?.uri.fsPath;
        const defaultFile = wsRoot
            ? vscode.Uri.file(path.join(wsRoot, '.claraity', 'claraity_knowledge.jsonl'))
            : undefined;
        const result = await vscode.window.showSaveDialog({
            defaultUri: defaultFile,
            saveLabel: 'Export Knowledge',
            filters: { 'Knowledge JSONL': ['jsonl'] },
        });
        if (!result) return;

        this.connection?.send({
            type: 'export_knowledge',
            path: result.fsPath,
        } as ClientMessage);
    }

    /**
     * Open native file picker for a .jsonl knowledge file, read its content,
     * and forward it to the backend for import. On success the backend sends
     * back an architecture_data response which auto-refreshes the panel.
     */
    private async importKnowledgeFromFile(): Promise<void> {
        const wsRoot = vscode.workspace.workspaceFolders?.[0]?.uri.fsPath;
        const defaultDir = wsRoot ? vscode.Uri.file(path.join(wsRoot, '.claraity')) : undefined;
        const result = await vscode.window.showOpenDialog({
            canSelectMany: false,
            canSelectFolders: false,
            openLabel: 'Import Knowledge',
            defaultUri: defaultDir,
            filters: { 'Knowledge JSONL': ['jsonl', 'json'] },
        });
        if (!result || result.length === 0) return;

        try {
            const content = await fs.promises.readFile(result[0].fsPath, 'utf-8');
            this.connection?.send({ type: 'import_knowledge', content } as ClientMessage);
        } catch (e: any) {
            vscode.window.showErrorMessage(`Failed to read file: ${e.message}`);
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
            } else if (toolName === 'append_to_file') {
                filePath = args.file_path || args.path || '';
                const appendContent = args.content || '';
                // Read existing file to show current content
                if (filePath) {
                    try {
                        const uri = vscode.Uri.file(filePath);
                        const bytes = await vscode.workspace.fs.readFile(uri);
                        originalContent = Buffer.from(bytes).toString('utf-8');
                    } catch {
                        originalContent = '';
                    }
                }
                // Modified = original + appended content
                if (originalContent && !originalContent.endsWith('\n')) {
                    modifiedContent = originalContent + '\n' + appendContent;
                } else {
                    modifiedContent = originalContent + appendContent;
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
            this.log?.appendLine('[ERROR] Failed to open diff editor: ' + err);
        }
    }

    /**
     * Search workspace files and send results to the WebView.
     * Used for @file mention autocomplete.
     */
    private async searchWorkspaceFiles(query: string): Promise<void> {
        try {
            const pattern = query ? `**/*${query}*` : '**/*';
            const uris = await vscode.workspace.findFiles(
                pattern,
                '**/node_modules/**',
                50,  // Max results
            );

            const workDir = vscode.workspace.workspaceFolders?.[0]?.uri.fsPath ?? '';
            const files = uris.map((uri) => {
                const fullPath = uri.fsPath;
                const name = fullPath.split(/[/\\]/).pop() || fullPath;
                const relativePath = workDir
                    ? fullPath.replace(workDir, '').replace(/^[/\\]/, '')
                    : fullPath;
                return { path: fullPath, name, relativePath };
            });

            // Sort by path length (shorter = more relevant), then alphabetically
            files.sort((a, b) => a.relativePath.length - b.relativePath.length || a.relativePath.localeCompare(b.relativePath));

            this.postToWebview({ type: 'fileSearchResults', files });
        } catch (err) {
            this.log?.appendLine('[ERROR] File search failed: ' + err);
            this.postToWebview({ type: 'fileSearchResults', files: [] });
        }
    }

    /**
     * Send a chat message with optional file attachments.
     * Reads file contents and prepends them to the message as context.
     */
    private async sendChatWithAttachments(
        content: string,
        attachments?: FileAttachment[],
        images?: ImageAttachment[],
        systemContext?: string,
    ): Promise<void> {
        // Prepend system context (hidden from UI, visible to agent)
        let finalContent = content;
        if (systemContext) {
            finalContent = `<system-context>\n${systemContext}\n</system-context>\n\n${content}`;
        }
        if (attachments && attachments.length > 0) {
            const fileParts: string[] = [];
            for (const attachment of attachments) {
                // Skip binary files as a safety net
                const ext = path.extname(attachment.name).toLowerCase();
                if (ClarAItySidebarProvider.BINARY_EXTENSIONS.has(ext)) continue;

                try {
                    let text: string;
                    if (attachment.content != null) {
                        // Inline content from paste/drop (no filesystem path)
                        text = attachment.content;
                    } else {
                        const uri = vscode.Uri.file(attachment.path);
                        const bytes = await vscode.workspace.fs.readFile(uri);
                        text = Buffer.from(bytes).toString('utf-8');
                    }
                    const safePath = attachment.path.replace(/"/g, '&quot;');
                    const safeName = attachment.name.replace(/"/g, '&quot;');
                    fileParts.push(
                        `<attached_file path="${safePath}" name="${safeName}">\n${text}\n</attached_file>`
                    );
                } catch (err) {
                    const safePath = attachment.path.replace(/"/g, '&quot;');
                    const safeName = attachment.name.replace(/"/g, '&quot;');
                    fileParts.push(
                        `<attached_file path="${safePath}" name="${safeName}">\n[Error reading file: ${err}]\n</attached_file>`
                    );
                }
            }
            const contextBlock = `<attached_files>\n${fileParts.join('\n')}\n</attached_files>\n\n`;
            finalContent = contextBlock + content;
        }

        // Build the server payload — images are sent as base64 data URLs
        // img.data is already a full data URL from FileReader.readAsDataURL()
        // (e.g., "data:image/png;base64,iVBOR..."), so pass it directly.
        const imagePayload = (images && images.length > 0)
            ? images.map(img => ({
                data_url: img.data,
                mime: img.mimeType,
                filename: img.name || 'screenshot.png',
            }))
            : undefined;

        this.connection?.send({
            type: 'chat_message',
            content: finalContent,
            ...(imagePayload ? { images: imagePayload } : {}),
        } as ClientMessage);
    }

    /**
     * Open diff editor from an external command (e.g., CodeLens).
     */
    openDiffFromCommand(callId: string, toolName: string, args: Record<string, any>): void {
        this.openDiffEditor(callId, toolName, args);
    }

    /**
     * Trigger session history panel from extension command.
     */
    showSessionHistory(): void {
        this.postToWebview({ type: 'showSessionHistory' });
    }

    showConfig(): void {
        this.postToWebview({ type: 'showConfig' });
    }

    showMcp(): void {
        this.postToWebview({ type: 'showMcp' });
    }

    showSubagents(): void {
        this.postToWebview({ type: 'showSubagents' });
    }


    postToWebview(message: ExtensionMessage): void {
        this.view?.webview.postMessage(message);
    }

    /**
     * Scan parent trace steps for subagent_start events, read the referenced
     * subagent .trace.jsonl files, and inline their steps after the bookend.
     * Each inlined step is tagged with _subagent and _isSubagentStep.
     * IDs are renumbered sequentially so the timeline stays contiguous.
     */
    private inlineSubagentTraces(steps: any[], sessionsDir: string): any[] {
        const result: any[] = [];
        for (const step of steps) {
            result.push(step);
            if (step.type === 'subagent_start' && step.sections?.trace_path) {
                // Construct the subagent trace path from sessionsDir + filename only.
                // The trace_path in JSONL was written by Python (different source than
                // VS Code's wsRoot), so absolute paths may not match (case, symlinks).
                // Using only the filename from the Python path and building the rest
                // from sessionsDir keeps both sides derived from VS Code.
                const pythonTracePath = step.sections.trace_path;
                const traceFilename = path.basename(pythonTracePath);

                // Validate filename: must end with .trace.jsonl, no path separators
                if (!traceFilename.endsWith('.trace.jsonl') || traceFilename.includes('..')) {
                    console.error('[ClarAIty] inlineSubagentTraces: invalid filename:', traceFilename);
                    continue;
                }

                const subTracePath = path.join(sessionsDir, 'subagents', traceFilename);
                try {
                    if (fs.existsSync(subTracePath)) {
                        const subRaw = fs.readFileSync(subTracePath, 'utf-8');
                        const subSteps = subRaw.trim().split('\n')
                            .filter(Boolean)
                            .map((line: string) => JSON.parse(line));
                        const subName = step.sections.subagent_name || 'subagent';
                        for (const subStep of subSteps) {
                            subStep._subagent = subName;
                            subStep._isSubagentStep = true;
                        }
                        result.push(...subSteps);
                    }
                } catch (err) {
                    console.error('[ClarAIty] Failed to read subagent trace:', err);
                }
            }
        }
        // Renumber IDs sequentially
        result.forEach((s, i) => { s.id = i + 1; });
        return result;
    }

    private getHtmlForWebview(webview: vscode.Webview): string {
        const webviewDistPath = vscode.Uri.joinPath(this.extensionUri, 'webview-ui', 'dist');
        const scriptFsPath = vscode.Uri.joinPath(webviewDistPath, 'webview.js').fsPath;

        // Check if React build exists — show helpful error if missing
        const fs = require('fs') as typeof import('fs');
        if (!fs.existsSync(scriptFsPath)) {
            this.log?.appendLine('[ClarAIty] Webview build not found at: ' + scriptFsPath);
            return `<!DOCTYPE html>
<html lang="en"><head><meta charset="UTF-8"></head>
<body style="padding:20px;color:var(--vscode-errorForeground,#f44);font-family:var(--vscode-font-family,sans-serif);">
<h3>ClarAIty: Webview not built</h3>
<p>The React webview bundle was not found.</p>
<p>Run: <code>cd webview-ui && npm run build</code></p>
<p>Then reload the VS Code window.</p>
</body></html>`;
        }

        const scriptUri = webview.asWebviewUri(
            vscode.Uri.joinPath(webviewDistPath, 'webview.js')
        );
        const styleUri = webview.asWebviewUri(
            vscode.Uri.joinPath(webviewDistPath, 'webview.css')
        );
        const codiconCssUri = webview.asWebviewUri(
            vscode.Uri.joinPath(this.extensionUri, 'media', 'codicon.css')
        );

        return `<!DOCTYPE html>
<html lang="en">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <meta http-equiv="Content-Security-Policy" content="default-src 'none'; style-src ${webview.cspSource} 'unsafe-inline'; script-src ${webview.cspSource}; font-src ${webview.cspSource} data:; img-src data:;">
    <link rel="stylesheet" href="${codiconCssUri}">
    <link rel="stylesheet" href="${styleUri}">
    <title>ClarAIty</title>
</head>
<body>
    <div id="root"></div>
    <script src="${scriptUri}"></script>
</body>
</html>`;
    }
}
