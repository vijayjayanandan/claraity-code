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

let connection: AgentConnection | undefined;
let serverManager: ServerManager | undefined;

export function activate(context: vscode.ExtensionContext) {
    console.log('[ClarAIty] Extension activating...');

    // Read configuration
    const config = vscode.workspace.getConfiguration('claraity');
    const serverUrl = config.get<string>('serverUrl', 'ws://localhost:9120/ws');
    const autoConnect = config.get<boolean>('autoConnect', true);
    const serverAutoStart = config.get<boolean>('serverAutoStart', true);
    const pythonPath = config.get<string>('pythonPath', 'python');

    // Extract port from serverUrl for the server manager
    const port = extractPort(serverUrl);

    // Create WebSocket connection
    connection = new AgentConnection(serverUrl);

    // Create sidebar provider
    const sidebarProvider = new ClarAItySidebarProvider(
        context.extensionUri,
        connection,
    );

    // Register the sidebar webview provider
    context.subscriptions.push(
        vscode.window.registerWebviewViewProvider(
            'claraity.chatView',
            sidebarProvider,
        ),
    );

    // Register commands
    context.subscriptions.push(
        vscode.commands.registerCommand('claraity.newChat', () => {
            // Focus the chat view
            vscode.commands.executeCommand('claraity.chatView.focus');
        }),
        vscode.commands.registerCommand('claraity.interrupt', () => {
            connection?.send({ type: 'interrupt' });
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
                        console.log('[ClarAIty] Server ready, connecting WebSocket...');
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
                    console.error('[ClarAIty] Environment resolution failed:', msg);
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

    console.log('[ClarAIty] Extension activated');
}

export function deactivate() {
    connection?.dispose();
    connection = undefined;
    serverManager?.dispose();
    serverManager = undefined;
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
