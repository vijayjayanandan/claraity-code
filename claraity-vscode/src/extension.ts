/**
 * ClarAIty VS Code Extension - Entry Point
 *
 * Activates when the ClarAIty sidebar view is opened.
 * Manages stdio connection and WebView lifecycle.
 */

import * as vscode from 'vscode';
import { ClarAItySidebarProvider } from './sidebar-provider';
import { resolveLaunchConfig } from './python-env';
import { ClarAItyFileDecorationProvider } from './file-decoration-provider';
import { ClarAItyCodeLensProvider } from './code-lens-provider';
import { UndoManager } from './undo-manager';
import { detectProjectContext, formatProjectContext } from './workspace-detector';
import { StdioConnection } from './stdio-connection';
import { ServerMessage } from './types';

let connection: StdioConnection | undefined;

export function activate(context: vscode.ExtensionContext) {
    // Create output channel for extension-side logging
    const log = vscode.window.createOutputChannel('ClarAIty Extension');
    context.subscriptions.push(log);
    log.appendLine('[ClarAIty] Extension activating...');

    // Read configuration
    const config = vscode.workspace.getConfiguration('claraity');
    const pythonPath = config.get<string>('pythonPath', 'python');
    const devMode = config.get<string>('devMode', 'auto');
    const autoInstallAgent = config.get<boolean>('autoInstallAgent', true);

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

    // Create sidebar provider (connection is null until stdio connects)
    const sidebarProvider = new ClarAItySidebarProvider(
        context.extensionUri,
        null,
        log,
    );
    sidebarProvider.setSecrets(context.secrets);

    // Register the sidebar webview provider
    context.subscriptions.push(
        vscode.window.registerWebviewViewProvider(
            'claraity.chatView',
            sidebarProvider,
        ),
    );

    /**
     * Wire a connection's events to the extension handlers (file decorations,
     * undo, terminal echo, sidebar, status bar). Called once when the stdio
     * connection is available.
     */
    function wireConnection(
        conn: StdioConnection,
        statusBar: vscode.StatusBarItem,
    ): void {
        // Track agent-modified files, pending changes, terminal commands, and undo checkpoints
        conn.onMessage((msg: ServerMessage) => {
            // Begin undo checkpoint on each agent turn
            if (msg.type === 'stream_start') {
                undoManager.beginCheckpoint();
            }

            if (msg.type === 'store' && msg.event === 'tool_state_updated') {
                const { call_id, tool_name, status, arguments: args } = msg.data;

                // File decorations and CodeLens
                if (tool_name === 'write_file' || tool_name === 'edit_file') {
                    if (status === 'awaiting_approval' && args) {
                        const filePath = (args.file_path || args.path) as string | undefined;
                        if (filePath) {
                            codeLens.addPendingChange(call_id, tool_name, filePath, args as Record<string, any>);
                            // Snapshot BEFORE any modification
                            undoManager.snapshotFile(filePath);
                        }
                    } else if (status === 'running' && args) {
                        // Auto-approve path — snapshot on running if not already done
                        const filePath = (args.file_path || args.path) as string | undefined;
                        if (filePath) {
                            undoManager.snapshotFile(filePath);
                        }
                    } else if (status === 'success' && args) {
                        const filePath = (args.file_path || args.path) as string | undefined;
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
                        if (shownCommands.size > 1000) { shownCommands.clear(); }
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

        // Update status bar on connection changes
        conn.onConnected(() => {
            statusBar.text = '$(sparkle) ClarAIty';
            statusBar.tooltip = 'ClarAIty - Connected';
        });
        conn.onDisconnected(() => {
            statusBar.text = '$(loading~spin) ClarAIty (reconnecting...)';
            statusBar.tooltip = 'ClarAIty - Reconnecting...';
            // If auto-restart fails, the connection will show an error dialog
            // and update status bar via the next onConnected or manual restart
            setTimeout(() => {
                // If still not connected after 15s, show offline
                if (!conn.isConnected) {
                    statusBar.text = '$(error) ClarAIty (offline)';
                    statusBar.tooltip = 'ClarAIty - Disconnected. Use "New Chat" to reconnect.';
                }
            }, 15_000);
        });
    }

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
            // Verify agent is alive — if dead, attempt restart
            if (connection && !connection.isConnected) {
                log.appendLine('[ClarAIty] Agent is dead on newChat — restarting');
                connection.restart();
            }
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
        vscode.commands.registerCommand('claraity.setApiKey', async () => {
            const key = await vscode.window.showInputBox({
                prompt: 'Enter your LLM API key',
                password: true,
                placeHolder: 'sk-...',
                ignoreFocusOut: true,
            });
            if (key !== undefined) {
                await context.secrets.store('claraity.apiKey', key);
                vscode.window.showInformationMessage(
                    key ? 'ClarAIty: API key saved. Restart the agent to apply.'
                         : 'ClarAIty: API key cleared.',
                );
            }
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

    // --- STDIO MODE ---
    const workDir = vscode.workspace.workspaceFolders?.[0]?.uri.fsPath;
    if (!workDir) {
        vscode.window.showWarningMessage(
            'ClarAIty: No workspace folder open. Cannot start in stdio mode.',
        );
        statusBar.text = '$(sparkle) ClarAIty (offline)';
        statusBar.tooltip = 'ClarAIty - No workspace folder';
    } else {
        statusBar.text = '$(loading~spin) ClarAIty (checking...)';
        statusBar.tooltip = 'ClarAIty - Detecting environment...';

        // Port is passed for resolveLaunchConfig compatibility (not used in stdio)
        const port = 9120;

        resolveLaunchConfig(pythonPath, port, workDir, devMode, autoInstallAgent)
            .then(async (launchConfig) => {
                if (!launchConfig) {
                    statusBar.text = '$(error) ClarAIty (not installed)';
                    statusBar.tooltip = 'ClarAIty - Agent not found';
                    return;
                }

                log.appendLine('[ClarAIty] Starting in stdio mode...');
                statusBar.text = '$(loading~spin) ClarAIty (starting...)';
                statusBar.tooltip = `ClarAIty - Starting (stdio, ${launchConfig.mode} mode)...`;

                // Create stdio connection with the resolved launch config
                const stdioConn = new StdioConnection(
                    {
                        command: launchConfig.command,
                        args: launchConfig.args,
                        cwd: launchConfig.cwd,
                    },
                    log,
                    context.extensionPath,
                );

                // Inject API key from VS Code SecretStorage
                const apiKey = await context.secrets.get('claraity.apiKey');
                if (apiKey) {
                    stdioConn.setApiKey(apiKey);
                    log.appendLine('[ClarAIty] API key loaded from SecretStorage');
                }

                // Inject Tavily key from VS Code SecretStorage
                const tavilyKey = await context.secrets.get('claraity.tavilyKey');
                if (tavilyKey) {
                    stdioConn.setTavilyKey(tavilyKey);
                    log.appendLine('[ClarAIty] Tavily key loaded from SecretStorage');
                }

                connection = stdioConn;

                // Wire events (message handler, status bar, sidebar)
                wireConnection(stdioConn, statusBar);
                sidebarProvider.setConnection(stdioConn);

                context.subscriptions.push(stdioConn);
                stdioConn.connect();
            })
            .catch((err) => {
                const msg = err instanceof Error ? err.message : String(err);
                log.appendLine('[ERROR] Stdio launch failed: ' + msg);
                statusBar.text = '$(error) ClarAIty (error)';
                statusBar.tooltip = `ClarAIty - ${msg}`;
            });
    }

    // Register cleanup
    context.subscriptions.push({
        dispose: () => {
            connection?.dispose();
        },
    });

    log.appendLine('[ClarAIty] Extension activated');
}

export async function deactivate() {
    if (connection) {
        connection.disconnect();
        // Wait briefly for the graceful shutdown before VS Code tears down
        await new Promise<void>((resolve) => setTimeout(resolve, 1000));
        connection.dispose();
        connection = undefined;
    }
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
