/**
 * ClarAIty VS Code Extension - Entry Point
 *
 * Activates when the ClarAIty sidebar view is opened.
 * Manages server lifecycle, WebSocket connection, and WebView lifecycle.
 */

import * as vscode from 'vscode';
import { ClarAItySidebarProvider } from './sidebar-provider';
import { AgentConnection } from './agent-connection';
import { ServerManager } from './server-manager';
import { resolveLaunchConfig } from './python-env';
import { ClarAItyFileDecorationProvider } from './file-decoration-provider';
import { ClarAItyCodeLensProvider } from './code-lens-provider';
import { UndoManager } from './undo-manager';
import { detectProjectContext, formatProjectContext } from './workspace-detector';
import { ServerMessage } from './types';

let connection: AgentConnection | undefined;
let serverManager: ServerManager | undefined;

export function activate(context: vscode.ExtensionContext) {
    // Create output channel for extension-side logging
    const log = vscode.window.createOutputChannel('ClarAIty Extension');
    context.subscriptions.push(log);
    log.appendLine('[ClarAIty] Extension activating...');

    // Read configuration
    const config = vscode.workspace.getConfiguration('claraity');
    const serverUrl = config.get<string>('serverUrl', 'ws://localhost:9120/ws');
    const autoConnect = config.get<boolean>('autoConnect', true);
    const serverAutoStart = config.get<boolean>('serverAutoStart', true);
    const pythonPath = config.get<string>('pythonPath', 'python');

    // Extract port from serverUrl for the server manager
    const port = extractPort(serverUrl);

    // Create WebSocket connection
    connection = new AgentConnection(serverUrl, log);

    // Create file decoration provider for marking agent-modified files
    const fileDecorations = new ClarAItyFileDecorationProvider();
    context.subscriptions.push(
        vscode.window.registerFileDecorationProvider(fileDecorations),
        fileDecorations,
    );

    // Create CodeLens provider for inline accept/reject
    const codeLens = new ClarAItyCodeLensProvider();
    context.subscriptions.push(
        vscode.languages.registerCodeLensProvider({ scheme: 'file' }, codeLens),
        codeLens,
    );

    // Undo manager for reverting agent file changes
    const undoManager = new UndoManager(log);
    context.subscriptions.push(undoManager);

    // Terminal for displaying agent commands
    let agentTerminal: vscode.Terminal | undefined;
    const shownCommands = new Set<string>(); // track call_ids to avoid duplicates

    function getAgentTerminal(): vscode.Terminal {
        // Reuse existing terminal if still alive
        if (agentTerminal && vscode.window.terminals.includes(agentTerminal)) {
            return agentTerminal;
        }
        agentTerminal = vscode.window.createTerminal({
            name: 'ClarAIty Commands',
            isTransient: true,
        });
        return agentTerminal;
    }

    // Track agent-modified files, pending changes, terminal commands, and undo checkpoints
    connection.onMessage((msg: ServerMessage) => {
        // Begin undo checkpoint on each agent turn
        if (msg.type === 'stream_start') {
            undoManager.beginCheckpoint();
        }

        if (msg.type === 'store' && msg.event === 'tool_state_updated') {
            const { call_id, tool_name, status, arguments: args } = msg.data;

            // File decorations and CodeLens
            if (tool_name === 'write_file' || tool_name === 'edit_file') {
                if (status === 'awaiting_approval' && args) {
                    const filePath = args.file_path || args.path;
                    if (filePath) {
                        codeLens.addPendingChange(call_id, tool_name, filePath, args);
                        // Snapshot BEFORE any modification
                        undoManager.snapshotFile(filePath);
                    }
                } else if (status === 'running' && args) {
                    // Auto-approve path — snapshot on running if not already done
                    const filePath = args.file_path || args.path;
                    if (filePath) {
                        undoManager.snapshotFile(filePath);
                    }
                } else if (status === 'success' && args) {
                    const filePath = args.file_path || args.path;
                    if (filePath) {
                        fileDecorations.markModified(filePath);
                    }
                    codeLens.removePendingChange(call_id);
                } else if (status === 'rejected' || status === 'error' || status === 'cancelled') {
                    codeLens.removePendingChange(call_id);
                }
            }

            // Terminal: echo run_command commands
            if (tool_name === 'run_command' && status === 'running' && args) {
                const command = args.command;
                if (command && !shownCommands.has(call_id)) {
                    shownCommands.add(call_id);
                    const terminal = getAgentTerminal();
                    // Echo the command as a comment (don't execute — runs server-side).
                    // Sanitize newlines to prevent shell injection.
                    const sanitized = String(command).replace(/[\r\n]+/g, ' ');
                    terminal.sendText(`# [ClarAIty] ${sanitized}`, true);
                }
            }
        }

        // Commit undo checkpoint when turn ends
        if (msg.type === 'stream_end') {
            const checkpoint = undoManager.commitCheckpoint();
            if (checkpoint) {
                const filePaths = Array.from(checkpoint.files.values()).map(f => f.path);
                sidebarProvider.postToWebview({
                    type: 'undoAvailable',
                    turnId: checkpoint.turnId,
                    files: filePaths,
                });
            }
        }

        // Clear state on new session
        if (msg.type === 'session_info') {
            fileDecorations.clear();
            codeLens.clear();
            shownCommands.clear();
            undoManager.clear();
        }
    });

    // Create sidebar provider
    const sidebarProvider = new ClarAItySidebarProvider(
        context.extensionUri,
        connection,
        log,
    );

    // Register the sidebar webview provider
    context.subscriptions.push(
        vscode.window.registerWebviewViewProvider(
            'claraity.chatView',
            sidebarProvider,
        ),
    );

    // Detect workspace context for first-message enrichment
    detectProjectContext().then((ctx) => {
        if (ctx) {
            const contextBlock = formatProjectContext(ctx);
            sidebarProvider.setProjectContext(contextBlock);
            log.appendLine(`[ClarAIty] Project: ${ctx.language}${ctx.framework ? ' / ' + ctx.framework : ''}`);
        }
    }).catch((err) => {
        log.appendLine(`[ClarAIty] Workspace detection failed: ${err}`);
    });

    // Register commands
    context.subscriptions.push(
        vscode.commands.registerCommand('claraity.newChat', () => {
            // Focus the chat view
            vscode.commands.executeCommand('claraity.chatView.focus');
        }),
        vscode.commands.registerCommand('claraity.interrupt', () => {
            connection?.send({ type: 'interrupt' });
        }),
        vscode.commands.registerCommand('claraity.sessionHistory', () => {
            sidebarProvider.showSessionHistory();
        }),
        vscode.commands.registerCommand('claraity.acceptChange', (callId: string) => {
            connection?.send({
                type: 'approval_result',
                call_id: callId,
                approved: true,
                auto_approve_future: false,
            });
            codeLens.removePendingChange(callId);
        }),
        vscode.commands.registerCommand('claraity.rejectChange', (callId: string) => {
            connection?.send({
                type: 'approval_result',
                call_id: callId,
                approved: false,
            });
            codeLens.removePendingChange(callId);
        }),
        vscode.commands.registerCommand('claraity.viewDiff', (callId: string, toolName: string, args: Record<string, any>) => {
            sidebarProvider.openDiffFromCommand(callId, toolName, args);
        }),
        vscode.commands.registerCommand('claraity.undoTurn', async (turnId: string) => {
            const restoredFiles = await undoManager.undo(turnId);
            sidebarProvider.postToWebview({
                type: 'undoComplete',
                turnId,
                restoredFiles,
            });
            if (restoredFiles.length > 0) {
                log.appendLine(`[ClarAIty] Undo: restored ${restoredFiles.length} file(s)`);
            }
        }),
        // Editor context menu commands
        vscode.commands.registerCommand('claraity.explainCode', () => {
            sendSelectionToChat(sidebarProvider, 'Explain this code:\n\n');
        }),
        vscode.commands.registerCommand('claraity.fixCode', () => {
            sendSelectionToChat(sidebarProvider, 'Fix this code:\n\n');
        }),
        vscode.commands.registerCommand('claraity.refactorCode', () => {
            sendSelectionToChat(sidebarProvider, 'Refactor this code:\n\n');
        }),
        vscode.commands.registerCommand('claraity.addToChat', () => {
            sendSelectionToChat(sidebarProvider, '');
        }),
    );

    // Status bar item
    const statusBar = vscode.window.createStatusBarItem(
        vscode.StatusBarAlignment.Left,
        100,
    );
    statusBar.command = 'claraity.newChat';
    statusBar.show();
    context.subscriptions.push(statusBar);

    // Update status bar on connection changes
    connection.onConnected(() => {
        statusBar.text = '$(sparkle) ClarAIty';
        statusBar.tooltip = 'ClarAIty - Connected';
    });
    connection.onDisconnected(() => {
        statusBar.text = '$(sparkle) ClarAIty (offline)';
        statusBar.tooltip = 'ClarAIty - Disconnected';
    });

    // Watch for config changes
    context.subscriptions.push(
        vscode.workspace.onDidChangeConfiguration((e) => {
            if (e.affectsConfiguration('claraity.serverUrl')) {
                const newUrl = vscode.workspace
                    .getConfiguration('claraity')
                    .get<string>('serverUrl', 'ws://localhost:9120/ws');
                connection?.updateUrl(newUrl);
            }
        }),
    );

    // Read environment detection settings
    const devMode = config.get<string>('devMode', 'auto');
    const autoInstallAgent = config.get<boolean>('autoInstallAgent', true);

    // Start server or connect directly
    if (serverAutoStart) {
        const workDir = vscode.workspace.workspaceFolders?.[0]?.uri.fsPath;
        if (!workDir) {
            vscode.window.showWarningMessage(
                'ClarAIty: No workspace folder open. Cannot auto-start server.',
            );
            // Fall back to manual connection
            statusBar.text = '$(sparkle) ClarAIty (offline)';
            statusBar.tooltip = 'ClarAIty - No workspace folder';
            if (autoConnect) {
                connection.connect();
            }
        } else {
            statusBar.text = '$(loading~spin) ClarAIty (checking...)';
            statusBar.tooltip = 'ClarAIty - Detecting environment...';

            resolveLaunchConfig(pythonPath, port, workDir, devMode, autoInstallAgent)
                .then((launchConfig) => {
                    if (!launchConfig) {
                        statusBar.text = '$(error) ClarAIty (not installed)';
                        statusBar.tooltip = 'ClarAIty - Agent not found';
                        return;
                    }

                    statusBar.text = '$(loading~spin) ClarAIty (starting...)';
                    statusBar.tooltip = `ClarAIty - Starting server (${launchConfig.mode} mode)...`;

                    serverManager = new ServerManager(launchConfig, port);

                    serverManager.onReady(() => {
                        log.appendLine('[ClarAIty] Server ready, connecting WebSocket...');
                        // Pass auth token for first-message handshake
                        const token = serverManager?.authToken;
                        if (token && connection) {
                            connection.setAuthToken(token);
                        }
                        connection?.connect();
                    });

                    serverManager.onStopped((reason) => {
                        statusBar.text = '$(error) ClarAIty (server error)';
                        statusBar.tooltip = `ClarAIty - Server stopped: ${reason}`;
                    });

                    context.subscriptions.push(serverManager);
                    serverManager.start();
                })
                .catch((err) => {
                    const msg = err instanceof Error ? err.message : String(err);
                    log.appendLine('[ERROR] Environment resolution failed: ' + msg);
                    statusBar.text = '$(error) ClarAIty (error)';
                    statusBar.tooltip = `ClarAIty - ${msg}`;
                });
        }
    } else {
        // Manual server mode -- existing behavior
        statusBar.text = '$(sparkle) ClarAIty';
        statusBar.tooltip = 'Open ClarAIty Chat';
        if (autoConnect) {
            connection.connect();
        }
    }

    // Register cleanup
    context.subscriptions.push({
        dispose: () => {
            connection?.dispose();
        },
    });

    log.appendLine('[ClarAIty] Extension activated');
}

export function deactivate() {
    connection?.dispose();
    connection = undefined;
    serverManager?.dispose();
    serverManager = undefined;
}

/**
 * Get the active editor's selection and send it to the chat sidebar
 * with an optional prompt prefix.
 */
function sendSelectionToChat(
    sidebarProvider: ClarAItySidebarProvider,
    promptPrefix: string,
): void {
    const editor = vscode.window.activeTextEditor;
    if (!editor || editor.selection.isEmpty) {
        vscode.window.showWarningMessage('ClarAIty: No text selected.');
        return;
    }

    const selectedText = editor.document.getText(editor.selection);
    const fileName = editor.document.fileName.split(/[/\\]/).pop() || '';
    const language = editor.document.languageId;
    const startLine = editor.selection.start.line + 1;
    const endLine = editor.selection.end.line + 1;

    // Build context block with file info + selected code
    const codeBlock = `\`\`\`${language}\n${selectedText}\n\`\`\``;
    const fileContext = `From \`${fileName}\` (lines ${startLine}-${endLine}):`;
    const content = promptPrefix
        ? `${promptPrefix}${fileContext}\n${codeBlock}`
        : `${fileContext}\n${codeBlock}`;

    // Focus the sidebar and send the message
    vscode.commands.executeCommand('claraity.chatView.focus');
    sidebarProvider.postToWebview({
        type: 'insertAndSend',
        content,
    });
}

/**
 * Extract port number from a WebSocket URL like "ws://localhost:9120/ws".
 * Falls back to 9120 if parsing fails.
 */
function extractPort(wsUrl: string): number {
    try {
        // Replace ws:// with http:// so URL constructor can parse it
        const httpUrl = wsUrl.replace(/^ws(s?):\/\//, 'http$1://');
        const parsed = new URL(httpUrl);
        const port = parseInt(parsed.port, 10);
        return isNaN(port) ? 9120 : port;
    } catch {
        return 9120;
    }
}
