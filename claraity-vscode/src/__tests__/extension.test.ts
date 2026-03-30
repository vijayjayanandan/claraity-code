/**
 * Comprehensive unit tests for extension.ts (activate / deactivate).
 *
 * Coverage:
 * - activate(): output channel, StdioConnection, SidebarProvider, webview
 *   registration, commands, status bar, connection event handlers (wireConnection),
 *   stdio launch scenarios, cleanup disposable, sendSelectionToChat
 * - deactivate(): disposes connection
 *
 * Total: 40+ tests covering all code paths in the stdio-only extension.ts
 */

import * as vscode from 'vscode';
import { activate, deactivate } from '../extension';

// ── Module mocks ────────────────────────────────────────────────────────────

jest.mock('../stdio-connection');
jest.mock('../sidebar-provider');
jest.mock('../python-env');
jest.mock('../file-decoration-provider');
jest.mock('../code-lens-provider');
jest.mock('../undo-manager');

import { StdioConnection } from '../stdio-connection';
import { ClarAItySidebarProvider } from '../sidebar-provider';
import { resolveLaunchConfig } from '../python-env';
import { ClarAItyFileDecorationProvider } from '../file-decoration-provider';
import { ClarAItyCodeLensProvider } from '../code-lens-provider';
import { UndoManager } from '../undo-manager';

// ── Types for mock instances ────────────────────────────────────────────────

interface MockStdioConnection {
    connect: jest.Mock;
    send: jest.Mock;
    dispose: jest.Mock;
    disconnect: jest.Mock;
    setApiKey: jest.Mock;
    setTavilyKey: jest.Mock;
    onConnected: jest.Mock;
    onDisconnected: jest.Mock;
    onMessage: jest.Mock;
    isConnected: boolean;
}

interface MockSidebarProvider {
    showSessionHistory: jest.Mock;
    setSecrets: jest.Mock;
    setConnection: jest.Mock;
    postToWebview: jest.Mock;
    openDiffFromCommand: jest.Mock;
}

interface MockFileDecorationProvider {
    markModified: jest.Mock;
    clear: jest.Mock;
    dispose: jest.Mock;
}

interface MockCodeLensProvider {
    addPendingChange: jest.Mock;
    removePendingChange: jest.Mock;
    clear: jest.Mock;
    dispose: jest.Mock;
}

interface MockUndoManager {
    beginCheckpoint: jest.Mock;
    commitCheckpoint: jest.Mock;
    snapshotFile: jest.Mock;
    undo: jest.Mock;
    clear: jest.Mock;
    dispose: jest.Mock;
}

// ── Helpers ─────────────────────────────────────────────────────────────────

/**
 * Build a fresh mock ExtensionContext with an empty subscriptions array.
 */
function createMockContext(): vscode.ExtensionContext {
    return {
        subscriptions: [],
        extensionUri: vscode.Uri.file('/mock/extension'),
        extensionPath: '/mock/extension',
        globalState: { get: jest.fn(), update: jest.fn(), keys: jest.fn(() => []), setKeysForSync: jest.fn() } as any,
        workspaceState: { get: jest.fn(), update: jest.fn(), keys: jest.fn(() => []) } as any,
        secrets: {
            get: jest.fn().mockResolvedValue(undefined),
            store: jest.fn().mockResolvedValue(undefined),
            delete: jest.fn().mockResolvedValue(undefined),
            onDidChange: jest.fn(),
        } as any,
        storagePath: '/mock/storage',
        globalStoragePath: '/mock/global-storage',
        logPath: '/mock/logs',
        extensionMode: 3, // Production
        storageUri: vscode.Uri.file('/mock/storage'),
        globalStorageUri: vscode.Uri.file('/mock/global-storage'),
        logUri: vscode.Uri.file('/mock/logs'),
        asAbsolutePath: jest.fn((p: string) => `/mock/extension/${p}`),
        environmentVariableCollection: {} as any,
        extension: {} as any,
        languageModelAccessInformation: {} as any,
    } as unknown as vscode.ExtensionContext;
}

/**
 * Stored callback registrations from mock event methods.
 * Allows tests to fire events (connected, disconnected, message)
 * after wireConnection has registered its listeners.
 */
let connectionCallbacks: Record<string, Function>;
let mockStdioInstance: MockStdioConnection;
let mockSidebarInstance: MockSidebarProvider;
let mockFileDecorationInstance: MockFileDecorationProvider;
let mockCodeLensInstance: MockCodeLensProvider;
let mockUndoManagerInstance: MockUndoManager;

function setupMocks() {
    connectionCallbacks = {};

    mockStdioInstance = {
        connect: jest.fn(),
        send: jest.fn(),
        dispose: jest.fn(),
        disconnect: jest.fn(),
        setApiKey: jest.fn(),
        setTavilyKey: jest.fn(),
        onConnected: jest.fn((cb: Function) => {
            connectionCallbacks['connected'] = cb;
            return { dispose: jest.fn() };
        }),
        onDisconnected: jest.fn((cb: Function) => {
            connectionCallbacks['disconnected'] = cb;
            return { dispose: jest.fn() };
        }),
        onMessage: jest.fn((cb: Function) => {
            connectionCallbacks['message'] = cb;
            return { dispose: jest.fn() };
        }),
        isConnected: false,
    };

    mockSidebarInstance = {
        showSessionHistory: jest.fn(),
        setSecrets: jest.fn(),
        setConnection: jest.fn(),
        postToWebview: jest.fn(),
        openDiffFromCommand: jest.fn(),
    };

    mockFileDecorationInstance = {
        markModified: jest.fn(),
        clear: jest.fn(),
        dispose: jest.fn(),
    };

    mockCodeLensInstance = {
        addPendingChange: jest.fn(),
        removePendingChange: jest.fn(),
        clear: jest.fn(),
        dispose: jest.fn(),
    };

    mockUndoManagerInstance = {
        beginCheckpoint: jest.fn(),
        commitCheckpoint: jest.fn().mockReturnValue(null),
        snapshotFile: jest.fn(),
        undo: jest.fn().mockResolvedValue([]),
        clear: jest.fn(),
        dispose: jest.fn(),
    };

    (StdioConnection as jest.Mock).mockImplementation(() => mockStdioInstance);
    (ClarAItySidebarProvider as unknown as jest.Mock).mockImplementation(() => mockSidebarInstance);
    (ClarAItyFileDecorationProvider as jest.Mock).mockImplementation(() => mockFileDecorationInstance);
    (ClarAItyCodeLensProvider as jest.Mock).mockImplementation(() => mockCodeLensInstance);
    (UndoManager as jest.Mock).mockImplementation(() => mockUndoManagerInstance);
    (resolveLaunchConfig as jest.Mock).mockResolvedValue(null);
}

/**
 * Set workspace folders. Pass undefined to simulate no workspace.
 */
function setWorkspaceFolders(folders: any[] | undefined) {
    (vscode.workspace as any).workspaceFolders = folders;
}

/**
 * Find a registered command callback by command ID.
 */
function findCommandCallback(commandId: string): Function | undefined {
    const calls = (vscode.commands.registerCommand as jest.Mock).mock.calls;
    const match = calls.find((c: any[]) => c[0] === commandId);
    return match ? match[1] : undefined;
}

// ── Test suite ──────────────────────────────────────────────────────────────

describe('extension.ts', () => {
    beforeEach(() => {
        jest.clearAllMocks();
        setupMocks();
        // Default: workspace folder exists
        setWorkspaceFolders([
            { uri: vscode.Uri.file('/test/workspace'), name: 'test', index: 0 },
        ]);
    });

    // ──────────────────────────────────────────────────────────────────────
    // activate() - basic setup
    // ──────────────────────────────────────────────────────────────────────

    describe('activate()', () => {
        describe('output channel', () => {
            test('creates output channel named "ClarAIty Extension"', () => {
                const ctx = createMockContext();
                activate(ctx);

                expect(vscode.window.createOutputChannel).toHaveBeenCalledWith(
                    'ClarAIty Extension',
                );
            });

            test('pushes output channel into subscriptions', () => {
                const ctx = createMockContext();
                activate(ctx);

                const channel = (vscode.window.createOutputChannel as jest.Mock).mock.results[0].value;
                expect(ctx.subscriptions).toContain(channel);
            });

            test('logs activation messages', () => {
                const ctx = createMockContext();
                activate(ctx);

                const channel = (vscode.window.createOutputChannel as jest.Mock).mock.results[0].value;
                expect(channel.appendLine).toHaveBeenCalledWith(
                    '[ClarAIty] Extension activating...',
                );
                expect(channel.appendLine).toHaveBeenCalledWith(
                    '[ClarAIty] Extension activated',
                );
            });
        });

        describe('ClarAItySidebarProvider', () => {
            test('creates sidebar provider with extensionUri, null connection, and log', () => {
                const ctx = createMockContext();
                activate(ctx);

                expect(ClarAItySidebarProvider).toHaveBeenCalledWith(
                    ctx.extensionUri,
                    null, // connection starts as null in stdio mode
                    expect.anything(), // output channel
                );
            });

            test('calls setSecrets on sidebar provider', () => {
                const ctx = createMockContext();
                activate(ctx);

                expect(mockSidebarInstance.setSecrets).toHaveBeenCalledWith(ctx.secrets);
            });
        });

        describe('file decoration provider', () => {
            test('creates and registers ClarAItyFileDecorationProvider', () => {
                const ctx = createMockContext();
                activate(ctx);

                expect(ClarAItyFileDecorationProvider).toHaveBeenCalled();
                expect(vscode.window.registerFileDecorationProvider).toHaveBeenCalledWith(
                    mockFileDecorationInstance,
                );
            });
        });

        describe('CodeLens provider', () => {
            test('creates and registers ClarAItyCodeLensProvider', () => {
                const ctx = createMockContext();
                activate(ctx);

                expect(ClarAItyCodeLensProvider).toHaveBeenCalled();
                expect(vscode.languages.registerCodeLensProvider).toHaveBeenCalledWith(
                    { scheme: 'file' },
                    mockCodeLensInstance,
                );
            });
        });

        describe('UndoManager', () => {
            test('creates UndoManager with log channel', () => {
                const ctx = createMockContext();
                activate(ctx);

                const channel = (vscode.window.createOutputChannel as jest.Mock).mock.results[0].value;
                expect(UndoManager).toHaveBeenCalledWith(channel);
            });
        });

        describe('webview registration', () => {
            test('registers webview view provider for "claraity.chatView"', () => {
                const ctx = createMockContext();
                activate(ctx);

                expect(vscode.window.registerWebviewViewProvider).toHaveBeenCalledWith(
                    'claraity.chatView',
                    mockSidebarInstance,
                );
            });

            test('pushes webview registration disposable into subscriptions', () => {
                const ctx = createMockContext();
                activate(ctx);

                const disposable = (vscode.window.registerWebviewViewProvider as jest.Mock)
                    .mock.results[0].value;
                expect(ctx.subscriptions).toContain(disposable);
            });
        });

        describe('command registration', () => {
            test('registers "claraity.newChat" command', () => {
                const ctx = createMockContext();
                activate(ctx);

                expect(vscode.commands.registerCommand).toHaveBeenCalledWith(
                    'claraity.newChat',
                    expect.any(Function),
                );
            });

            test('registers "claraity.interrupt" command', () => {
                const ctx = createMockContext();
                activate(ctx);

                expect(vscode.commands.registerCommand).toHaveBeenCalledWith(
                    'claraity.interrupt',
                    expect.any(Function),
                );
            });

            test('registers "claraity.sessionHistory" command', () => {
                const ctx = createMockContext();
                activate(ctx);

                expect(vscode.commands.registerCommand).toHaveBeenCalledWith(
                    'claraity.sessionHistory',
                    expect.any(Function),
                );
            });

            test('registers "claraity.setApiKey" command', () => {
                const ctx = createMockContext();
                activate(ctx);

                expect(vscode.commands.registerCommand).toHaveBeenCalledWith(
                    'claraity.setApiKey',
                    expect.any(Function),
                );
            });

            test('registers all 12 commands', () => {
                const ctx = createMockContext();
                activate(ctx);

                // newChat, interrupt, sessionHistory, acceptChange, rejectChange,
                // viewDiff, undoTurn, explainCode, fixCode, refactorCode, addToChat, setApiKey
                expect(vscode.commands.registerCommand).toHaveBeenCalledTimes(12);
            });

            test('newChat command focuses the chat view', () => {
                const ctx = createMockContext();
                activate(ctx);

                const callback = findCommandCallback('claraity.newChat');
                expect(callback).toBeDefined();
                callback!();

                expect(vscode.commands.executeCommand).toHaveBeenCalledWith(
                    'claraity.chatView.focus',
                );
            });

            test('sessionHistory command calls showSessionHistory on sidebar provider', () => {
                const ctx = createMockContext();
                activate(ctx);

                const callback = findCommandCallback('claraity.sessionHistory');
                expect(callback).toBeDefined();
                callback!();

                expect(mockSidebarInstance.showSessionHistory).toHaveBeenCalled();
            });

            test('pushes all command disposables into subscriptions', () => {
                const ctx = createMockContext();
                activate(ctx);

                const disposables = (vscode.commands.registerCommand as jest.Mock)
                    .mock.results.map((r: any) => r.value);
                for (const d of disposables) {
                    expect(ctx.subscriptions).toContain(d);
                }
            });
        });

        describe('status bar', () => {
            test('creates status bar item with Left alignment and priority 100', () => {
                const ctx = createMockContext();
                activate(ctx);

                expect(vscode.window.createStatusBarItem).toHaveBeenCalledWith(
                    vscode.StatusBarAlignment.Left,
                    100,
                );
            });

            test('sets status bar command to claraity.newChat', () => {
                const ctx = createMockContext();
                activate(ctx);

                const statusBar = (vscode.window.createStatusBarItem as jest.Mock)
                    .mock.results[0].value;
                expect(statusBar.command).toBe('claraity.newChat');
            });

            test('shows the status bar', () => {
                const ctx = createMockContext();
                activate(ctx);

                const statusBar = (vscode.window.createStatusBarItem as jest.Mock)
                    .mock.results[0].value;
                expect(statusBar.show).toHaveBeenCalled();
            });

            test('pushes status bar into subscriptions', () => {
                const ctx = createMockContext();
                activate(ctx);

                const statusBar = (vscode.window.createStatusBarItem as jest.Mock)
                    .mock.results[0].value;
                expect(ctx.subscriptions).toContain(statusBar);
            });
        });

        describe('cleanup disposable', () => {
            test('pushes a cleanup disposable into subscriptions', () => {
                const ctx = createMockContext();
                activate(ctx);

                // The last subscription should be the cleanup disposable
                const lastDisposable = ctx.subscriptions[ctx.subscriptions.length - 1] as any;
                expect(typeof lastDisposable.dispose).toBe('function');
            });
        });
    });

    // ──────────────────────────────────────────────────────────────────────
    // activate() - stdio mode with workspace
    // ──────────────────────────────────────────────────────────────────────

    describe('activate() - stdio mode with workspace', () => {
        test('calls resolveLaunchConfig with correct arguments', () => {
            const ctx = createMockContext();
            activate(ctx);

            expect(resolveLaunchConfig).toHaveBeenCalledWith(
                'python',   // default pythonPath
                9120,       // port (for compatibility)
                '/test/workspace',
                'auto',     // default devMode
                true,       // default autoInstallAgent
            );
        });

        test('sets status bar to checking state initially', () => {
            const ctx = createMockContext();
            activate(ctx);

            const statusBar = (vscode.window.createStatusBarItem as jest.Mock)
                .mock.results[0].value;
            expect(statusBar.text).toBe('$(loading~spin) ClarAIty (checking...)');
            expect(statusBar.tooltip).toBe('ClarAIty - Detecting environment...');
        });

        test('creates StdioConnection when launch config resolves', async () => {
            const launchConfig = {
                mode: 'dev' as const,
                command: 'python',
                args: ['-m', 'src.server'],
                cwd: '/test/workspace',
            };
            (resolveLaunchConfig as jest.Mock).mockResolvedValue(launchConfig);

            const ctx = createMockContext();
            activate(ctx);

            await flushPromises();

            expect(StdioConnection).toHaveBeenCalledWith(
                {
                    command: 'python',
                    args: ['-m', 'src.server'],
                    cwd: '/test/workspace',
                },
                expect.anything(), // log channel
                '/mock/extension', // extensionPath
            );
        });

        test('injects API key from SecretStorage when available', async () => {
            const launchConfig = {
                mode: 'dev' as const,
                command: 'python',
                args: ['-m', 'src.server'],
                cwd: '/test/workspace',
            };
            (resolveLaunchConfig as jest.Mock).mockResolvedValue(launchConfig);

            const ctx = createMockContext();
            (ctx.secrets.get as jest.Mock).mockImplementation((key: string) => {
                if (key === 'claraity.apiKey') { return Promise.resolve('sk-test-key'); }
                return Promise.resolve(undefined);
            });
            activate(ctx);

            await flushPromises();

            expect(mockStdioInstance.setApiKey).toHaveBeenCalledWith('sk-test-key');
        });

        test('injects Tavily key from SecretStorage when available', async () => {
            const launchConfig = {
                mode: 'dev' as const,
                command: 'python',
                args: ['-m', 'src.server'],
                cwd: '/test/workspace',
            };
            (resolveLaunchConfig as jest.Mock).mockResolvedValue(launchConfig);

            const ctx = createMockContext();
            (ctx.secrets.get as jest.Mock).mockImplementation((key: string) => {
                if (key === 'claraity.tavilyKey') { return Promise.resolve('tvly-test-key'); }
                return Promise.resolve(undefined);
            });
            activate(ctx);

            await flushPromises();

            expect(mockStdioInstance.setTavilyKey).toHaveBeenCalledWith('tvly-test-key');
        });

        test('does not inject API key when SecretStorage has none', async () => {
            const launchConfig = {
                mode: 'dev' as const,
                command: 'python',
                args: ['-m', 'src.server'],
                cwd: '/test/workspace',
            };
            (resolveLaunchConfig as jest.Mock).mockResolvedValue(launchConfig);

            const ctx = createMockContext();
            // secrets.get returns undefined by default
            activate(ctx);

            await flushPromises();

            expect(mockStdioInstance.setApiKey).not.toHaveBeenCalled();
        });

        test('wires connection and sets it on sidebar provider', async () => {
            const launchConfig = {
                mode: 'dev' as const,
                command: 'python',
                args: ['-m', 'src.server'],
                cwd: '/test/workspace',
            };
            (resolveLaunchConfig as jest.Mock).mockResolvedValue(launchConfig);

            const ctx = createMockContext();
            activate(ctx);

            await flushPromises();

            // wireConnection registers event handlers
            expect(mockStdioInstance.onMessage).toHaveBeenCalledTimes(1);
            expect(mockStdioInstance.onConnected).toHaveBeenCalledTimes(1);
            expect(mockStdioInstance.onDisconnected).toHaveBeenCalledTimes(1);

            // Sidebar gets the connection
            expect(mockSidebarInstance.setConnection).toHaveBeenCalledWith(mockStdioInstance);
        });

        test('calls connect on StdioConnection', async () => {
            const launchConfig = {
                mode: 'dev' as const,
                command: 'python',
                args: ['-m', 'src.server'],
                cwd: '/test/workspace',
            };
            (resolveLaunchConfig as jest.Mock).mockResolvedValue(launchConfig);

            const ctx = createMockContext();
            activate(ctx);

            await flushPromises();

            expect(mockStdioInstance.connect).toHaveBeenCalled();
        });

        test('pushes StdioConnection into subscriptions', async () => {
            const launchConfig = {
                mode: 'dev' as const,
                command: 'python',
                args: ['-m', 'src.server'],
                cwd: '/test/workspace',
            };
            (resolveLaunchConfig as jest.Mock).mockResolvedValue(launchConfig);

            const ctx = createMockContext();
            activate(ctx);

            await flushPromises();

            expect(ctx.subscriptions).toContain(mockStdioInstance);
        });

        test('updates status bar to starting state after launch config resolves', async () => {
            const launchConfig = {
                mode: 'dev' as const,
                command: 'python',
                args: ['-m', 'src.server'],
                cwd: '/test/workspace',
            };
            (resolveLaunchConfig as jest.Mock).mockResolvedValue(launchConfig);

            const ctx = createMockContext();
            activate(ctx);

            await flushPromises();

            const statusBar = (vscode.window.createStatusBarItem as jest.Mock)
                .mock.results[0].value;
            expect(statusBar.text).toBe('$(loading~spin) ClarAIty (starting...)');
            expect(statusBar.tooltip).toContain('Starting');
            expect(statusBar.tooltip).toContain('stdio');
            expect(statusBar.tooltip).toContain('dev mode');
        });

        test('shows not-installed status when resolveLaunchConfig returns null', async () => {
            (resolveLaunchConfig as jest.Mock).mockResolvedValue(null);

            const ctx = createMockContext();
            activate(ctx);

            await flushPromises();

            const statusBar = (vscode.window.createStatusBarItem as jest.Mock)
                .mock.results[0].value;
            expect(statusBar.text).toBe('$(error) ClarAIty (not installed)');
            expect(statusBar.tooltip).toBe('ClarAIty - Agent not found');
        });

        test('does not create StdioConnection when resolveLaunchConfig returns null', async () => {
            (resolveLaunchConfig as jest.Mock).mockResolvedValue(null);

            const ctx = createMockContext();
            activate(ctx);

            await flushPromises();

            expect(StdioConnection).not.toHaveBeenCalled();
        });

        test('handles resolveLaunchConfig rejection gracefully', async () => {
            (resolveLaunchConfig as jest.Mock).mockRejectedValue(
                new Error('Python not found'),
            );

            const ctx = createMockContext();
            activate(ctx);

            await flushPromises();

            const statusBar = (vscode.window.createStatusBarItem as jest.Mock)
                .mock.results[0].value;
            expect(statusBar.text).toBe('$(error) ClarAIty (error)');
            expect(statusBar.tooltip).toBe('ClarAIty - Python not found');
        });

        test('handles non-Error rejection gracefully', async () => {
            (resolveLaunchConfig as jest.Mock).mockRejectedValue('string error');

            const ctx = createMockContext();
            activate(ctx);

            await flushPromises();

            const statusBar = (vscode.window.createStatusBarItem as jest.Mock)
                .mock.results[0].value;
            expect(statusBar.text).toBe('$(error) ClarAIty (error)');
            expect(statusBar.tooltip).toBe('ClarAIty - string error');
        });

        test('logs error when resolveLaunchConfig rejects', async () => {
            (resolveLaunchConfig as jest.Mock).mockRejectedValue(
                new Error('Unexpected failure'),
            );

            const ctx = createMockContext();
            activate(ctx);

            await flushPromises();

            const channel = (vscode.window.createOutputChannel as jest.Mock)
                .mock.results[0].value;
            expect(channel.appendLine).toHaveBeenCalledWith(
                '[ERROR] Stdio launch failed: Unexpected failure',
            );
        });
    });

    // ──────────────────────────────────────────────────────────────────────
    // activate() - no workspace folder
    // ──────────────────────────────────────────────────────────────────────

    describe('activate() - no workspace folder', () => {
        test('shows warning message when no workspace folder', () => {
            setWorkspaceFolders(undefined);
            const ctx = createMockContext();
            activate(ctx);

            expect(vscode.window.showWarningMessage).toHaveBeenCalledWith(
                'ClarAIty: No workspace folder open. Cannot start in stdio mode.',
            );
        });

        test('sets status bar to offline when no workspace folder', () => {
            setWorkspaceFolders(undefined);
            const ctx = createMockContext();
            activate(ctx);

            const statusBar = (vscode.window.createStatusBarItem as jest.Mock)
                .mock.results[0].value;
            expect(statusBar.text).toBe('$(sparkle) ClarAIty (offline)');
            expect(statusBar.tooltip).toBe('ClarAIty - No workspace folder');
        });

        test('does not call resolveLaunchConfig when no workspace', () => {
            setWorkspaceFolders(undefined);
            const ctx = createMockContext();
            activate(ctx);

            expect(resolveLaunchConfig).not.toHaveBeenCalled();
        });

        test('does not create StdioConnection when no workspace', () => {
            setWorkspaceFolders(undefined);
            const ctx = createMockContext();
            activate(ctx);

            expect(StdioConnection).not.toHaveBeenCalled();
        });

        test('handles empty workspace folders array', () => {
            setWorkspaceFolders([]);
            const ctx = createMockContext();
            activate(ctx);

            // workspaceFolders[0] is undefined, so no workDir
            expect(vscode.window.showWarningMessage).toHaveBeenCalledWith(
                'ClarAIty: No workspace folder open. Cannot start in stdio mode.',
            );
        });
    });

    // ──────────────────────────────────────────────────────────────────────
    // wireConnection() - connection event handlers
    // ──────────────────────────────────────────────────────────────────────

    describe('wireConnection() - connection events', () => {
        async function activateWithConnection(): Promise<vscode.ExtensionContext> {
            const launchConfig = {
                mode: 'dev' as const,
                command: 'python',
                args: ['-m', 'src.server'],
                cwd: '/test/workspace',
            };
            (resolveLaunchConfig as jest.Mock).mockResolvedValue(launchConfig);

            const ctx = createMockContext();
            activate(ctx);
            await flushPromises();
            return ctx;
        }

        test('updates status bar text on connected event', async () => {
            await activateWithConnection();

            const statusBar = (vscode.window.createStatusBarItem as jest.Mock)
                .mock.results[0].value;

            expect(connectionCallbacks['connected']).toBeDefined();
            connectionCallbacks['connected']();

            expect(statusBar.text).toBe('$(sparkle) ClarAIty');
            expect(statusBar.tooltip).toBe('ClarAIty - Connected');
        });

        test('updates status bar text on disconnected event', async () => {
            await activateWithConnection();

            const statusBar = (vscode.window.createStatusBarItem as jest.Mock)
                .mock.results[0].value;

            expect(connectionCallbacks['disconnected']).toBeDefined();
            connectionCallbacks['disconnected']();

            expect(statusBar.text).toBe('$(sparkle) ClarAIty (offline)');
            expect(statusBar.tooltip).toBe('ClarAIty - Disconnected');
        });

        test('handles stream_start message by beginning undo checkpoint', async () => {
            await activateWithConnection();

            expect(connectionCallbacks['message']).toBeDefined();
            connectionCallbacks['message']({ type: 'stream_start' });

            expect(mockUndoManagerInstance.beginCheckpoint).toHaveBeenCalled();
        });

        test('handles stream_end message by committing undo checkpoint', async () => {
            await activateWithConnection();

            connectionCallbacks['message']({ type: 'stream_end' });

            expect(mockUndoManagerInstance.commitCheckpoint).toHaveBeenCalled();
        });

        test('posts undoAvailable to webview when checkpoint has files', async () => {
            mockUndoManagerInstance.commitCheckpoint.mockReturnValue({
                turnId: 'turn-1',
                files: new Map([['file1', { path: '/test/file.ts' }]]),
            });

            await activateWithConnection();

            connectionCallbacks['message']({ type: 'stream_end' });

            expect(mockSidebarInstance.postToWebview).toHaveBeenCalledWith({
                type: 'undoAvailable',
                turnId: 'turn-1',
                files: ['/test/file.ts'],
            });
        });

        test('handles tool_state_updated for write_file awaiting_approval', async () => {
            await activateWithConnection();

            connectionCallbacks['message']({
                type: 'store',
                event: 'tool_state_updated',
                data: {
                    call_id: 'call-1',
                    tool_name: 'write_file',
                    status: 'awaiting_approval',
                    arguments: { file_path: '/test/new-file.ts' },
                },
            });

            expect(mockCodeLensInstance.addPendingChange).toHaveBeenCalledWith(
                'call-1', 'write_file', '/test/new-file.ts',
                { file_path: '/test/new-file.ts' },
            );
            expect(mockUndoManagerInstance.snapshotFile).toHaveBeenCalledWith('/test/new-file.ts');
        });

        test('handles tool_state_updated for edit_file success', async () => {
            await activateWithConnection();

            connectionCallbacks['message']({
                type: 'store',
                event: 'tool_state_updated',
                data: {
                    call_id: 'call-2',
                    tool_name: 'edit_file',
                    status: 'success',
                    arguments: { file_path: '/test/edited.ts' },
                },
            });

            expect(mockFileDecorationInstance.markModified).toHaveBeenCalledWith('/test/edited.ts');
            expect(mockCodeLensInstance.removePendingChange).toHaveBeenCalledWith('call-2');
        });

        test('handles tool_state_updated for rejected status', async () => {
            await activateWithConnection();

            connectionCallbacks['message']({
                type: 'store',
                event: 'tool_state_updated',
                data: {
                    call_id: 'call-3',
                    tool_name: 'write_file',
                    status: 'rejected',
                    arguments: { file_path: '/test/file.ts' },
                },
            });

            expect(mockCodeLensInstance.removePendingChange).toHaveBeenCalledWith('call-3');
        });

        test('handles session_info by clearing all state', async () => {
            await activateWithConnection();

            connectionCallbacks['message']({ type: 'session_info' });

            expect(mockFileDecorationInstance.clear).toHaveBeenCalled();
            expect(mockCodeLensInstance.clear).toHaveBeenCalled();
            expect(mockUndoManagerInstance.clear).toHaveBeenCalled();
        });

        test('handles tool_state_updated for running status (auto-approve snapshot)', async () => {
            await activateWithConnection();

            connectionCallbacks['message']({
                type: 'store',
                event: 'tool_state_updated',
                data: {
                    call_id: 'call-4',
                    tool_name: 'write_file',
                    status: 'running',
                    arguments: { file_path: '/test/auto-file.ts' },
                },
            });

            expect(mockUndoManagerInstance.snapshotFile).toHaveBeenCalledWith('/test/auto-file.ts');
        });
    });

    // ──────────────────────────────────────────────────────────────────────
    // activate() - interrupt command with connection
    // ──────────────────────────────────────────────────────────────────────

    describe('interrupt command', () => {
        test('sends interrupt message via connection when connection exists', async () => {
            const launchConfig = {
                mode: 'dev' as const,
                command: 'python',
                args: ['-m', 'src.server'],
                cwd: '/test/workspace',
            };
            (resolveLaunchConfig as jest.Mock).mockResolvedValue(launchConfig);

            const ctx = createMockContext();
            activate(ctx);
            await flushPromises();

            const callback = findCommandCallback('claraity.interrupt');
            expect(callback).toBeDefined();
            callback!();

            expect(mockStdioInstance.send).toHaveBeenCalledWith({
                type: 'interrupt',
            });
        });

        test('does not throw when connection is not yet established', () => {
            // resolveLaunchConfig returns null, so no connection
            const ctx = createMockContext();
            activate(ctx);

            const callback = findCommandCallback('claraity.interrupt');
            expect(callback).toBeDefined();

            // Should not throw (connection?.send uses optional chaining)
            expect(() => callback!()).not.toThrow();
        });
    });

    // ──────────────────────────────────────────────────────────────────────
    // activate() - acceptChange, rejectChange, viewDiff, undoTurn commands
    // ──────────────────────────────────────────────────────────────────────

    describe('approval commands', () => {
        test('acceptChange sends approval_result and removes CodeLens', async () => {
            const launchConfig = {
                mode: 'dev' as const,
                command: 'python',
                args: ['-m', 'src.server'],
                cwd: '/test/workspace',
            };
            (resolveLaunchConfig as jest.Mock).mockResolvedValue(launchConfig);

            const ctx = createMockContext();
            activate(ctx);
            await flushPromises();

            const callback = findCommandCallback('claraity.acceptChange');
            expect(callback).toBeDefined();
            callback!('call-abc');

            expect(mockStdioInstance.send).toHaveBeenCalledWith({
                type: 'approval_result',
                call_id: 'call-abc',
                approved: true,
                auto_approve_future: false,
            });
            expect(mockCodeLensInstance.removePendingChange).toHaveBeenCalledWith('call-abc');
        });

        test('rejectChange sends rejection and removes CodeLens', async () => {
            const launchConfig = {
                mode: 'dev' as const,
                command: 'python',
                args: ['-m', 'src.server'],
                cwd: '/test/workspace',
            };
            (resolveLaunchConfig as jest.Mock).mockResolvedValue(launchConfig);

            const ctx = createMockContext();
            activate(ctx);
            await flushPromises();

            const callback = findCommandCallback('claraity.rejectChange');
            expect(callback).toBeDefined();
            callback!('call-xyz');

            expect(mockStdioInstance.send).toHaveBeenCalledWith({
                type: 'approval_result',
                call_id: 'call-xyz',
                approved: false,
            });
            expect(mockCodeLensInstance.removePendingChange).toHaveBeenCalledWith('call-xyz');
        });

        test('viewDiff delegates to sidebar provider', () => {
            const ctx = createMockContext();
            activate(ctx);

            const callback = findCommandCallback('claraity.viewDiff');
            expect(callback).toBeDefined();
            callback!('call-diff', 'write_file', { file_path: '/a.ts' });

            expect(mockSidebarInstance.openDiffFromCommand).toHaveBeenCalledWith(
                'call-diff', 'write_file', { file_path: '/a.ts' },
            );
        });

        test('undoTurn restores files and posts undoComplete', async () => {
            mockUndoManagerInstance.undo.mockResolvedValue(['/a.ts', '/b.ts']);

            const ctx = createMockContext();
            activate(ctx);

            const callback = findCommandCallback('claraity.undoTurn');
            expect(callback).toBeDefined();
            await callback!('turn-42');

            expect(mockUndoManagerInstance.undo).toHaveBeenCalledWith('turn-42');
            expect(mockSidebarInstance.postToWebview).toHaveBeenCalledWith({
                type: 'undoComplete',
                turnId: 'turn-42',
                restoredFiles: ['/a.ts', '/b.ts'],
            });
        });
    });

    // ──────────────────────────────────────────────────────────────────────
    // sendSelectionToChat (via editor context menu commands)
    // ──────────────────────────────────────────────────────────────────────

    describe('sendSelectionToChat commands', () => {
        function setupEditor(text: string, languageId: string, fileName: string) {
            (vscode.window as any).activeTextEditor = {
                selection: {
                    isEmpty: false,
                    start: { line: 4, character: 0 },
                    end: { line: 9, character: 0 },
                },
                document: {
                    getText: jest.fn(() => text),
                    fileName,
                    languageId,
                },
            };
        }

        test('explainCode sends selection with "Explain this code" prefix', () => {
            const ctx = createMockContext();
            activate(ctx);

            setupEditor('const x = 1;', 'typescript', '/test/workspace/file.ts');

            const callback = findCommandCallback('claraity.explainCode');
            callback!();

            expect(vscode.commands.executeCommand).toHaveBeenCalledWith('claraity.chatView.focus');
            expect(mockSidebarInstance.postToWebview).toHaveBeenCalledWith(
                expect.objectContaining({
                    type: 'insertAndSend',
                    content: expect.stringContaining('Explain this code:'),
                }),
            );
        });

        test('fixCode sends selection with "Fix this code" prefix', () => {
            const ctx = createMockContext();
            activate(ctx);

            setupEditor('buggy()', 'javascript', '/test/workspace/app.js');

            const callback = findCommandCallback('claraity.fixCode');
            callback!();

            expect(mockSidebarInstance.postToWebview).toHaveBeenCalledWith(
                expect.objectContaining({
                    type: 'insertAndSend',
                    content: expect.stringContaining('Fix this code:'),
                }),
            );
        });

        test('refactorCode sends selection with "Refactor this code" prefix', () => {
            const ctx = createMockContext();
            activate(ctx);

            setupEditor('old_code()', 'python', '/test/workspace/main.py');

            const callback = findCommandCallback('claraity.refactorCode');
            callback!();

            expect(mockSidebarInstance.postToWebview).toHaveBeenCalledWith(
                expect.objectContaining({
                    type: 'insertAndSend',
                    content: expect.stringContaining('Refactor this code:'),
                }),
            );
        });

        test('addToChat sends selection without prefix', () => {
            const ctx = createMockContext();
            activate(ctx);

            setupEditor('some_code()', 'typescript', '/test/workspace/utils.ts');

            const callback = findCommandCallback('claraity.addToChat');
            callback!();

            expect(mockSidebarInstance.postToWebview).toHaveBeenCalledWith(
                expect.objectContaining({
                    type: 'insertAndSend',
                    content: expect.stringContaining('utils.ts'),
                }),
            );
        });

        test('shows warning when no text selected', () => {
            const ctx = createMockContext();
            activate(ctx);

            (vscode.window as any).activeTextEditor = {
                selection: { isEmpty: true },
                document: { getText: jest.fn(), fileName: 'test.ts', languageId: 'typescript' },
            };

            const callback = findCommandCallback('claraity.explainCode');
            callback!();

            expect(vscode.window.showWarningMessage).toHaveBeenCalledWith(
                'ClarAIty: No text selected.',
            );
        });

        test('shows warning when no active editor', () => {
            const ctx = createMockContext();
            activate(ctx);

            (vscode.window as any).activeTextEditor = undefined;

            const callback = findCommandCallback('claraity.explainCode');
            callback!();

            expect(vscode.window.showWarningMessage).toHaveBeenCalledWith(
                'ClarAIty: No text selected.',
            );
        });

        test('includes file context with line numbers in content', () => {
            const ctx = createMockContext();
            activate(ctx);

            setupEditor('const x = 1;', 'typescript', '/test/workspace/src/index.ts');

            const callback = findCommandCallback('claraity.addToChat');
            callback!();

            const postCall = mockSidebarInstance.postToWebview.mock.calls[0][0];
            // Lines are 1-indexed: start.line(4)+1=5, end.line(9)+1=10
            expect(postCall.content).toContain('index.ts');
            expect(postCall.content).toContain('lines 5-10');
            expect(postCall.content).toContain('```typescript');
        });
    });

    // ──────────────────────────────────────────────────────────────────────
    // setApiKey command
    // ──────────────────────────────────────────────────────────────────────

    describe('setApiKey command', () => {
        test('stores key in SecretStorage when user provides one', async () => {
            (vscode.window as any).showInputBox = jest.fn().mockResolvedValue('sk-my-key');

            const ctx = createMockContext();
            activate(ctx);

            const callback = findCommandCallback('claraity.setApiKey');
            expect(callback).toBeDefined();
            await callback!();

            expect(ctx.secrets.store).toHaveBeenCalledWith('claraity.apiKey', 'sk-my-key');
        });

        test('does nothing when user cancels input', async () => {
            (vscode.window as any).showInputBox = jest.fn().mockResolvedValue(undefined);

            const ctx = createMockContext();
            activate(ctx);

            const callback = findCommandCallback('claraity.setApiKey');
            await callback!();

            expect(ctx.secrets.store).not.toHaveBeenCalled();
        });
    });

    // ──────────────────────────────────────────────────────────────────────
    // deactivate()
    // ──────────────────────────────────────────────────────────────────────

    describe('deactivate()', () => {
        test('disposes connection when active', async () => {
            const launchConfig = {
                mode: 'dev' as const,
                command: 'python',
                args: ['-m', 'src.server'],
                cwd: '/test/workspace',
            };
            (resolveLaunchConfig as jest.Mock).mockResolvedValue(launchConfig);

            const ctx = createMockContext();
            activate(ctx);
            await flushPromises();

            deactivate();

            expect(mockStdioInstance.dispose).toHaveBeenCalled();
        });

        test('does not throw when called without prior activation', () => {
            // Reset module-level state
            deactivate();
            // Calling again should not throw
            expect(() => deactivate()).not.toThrow();
        });

        test('sets connection to undefined after deactivation', async () => {
            const launchConfig = {
                mode: 'dev' as const,
                command: 'python',
                args: ['-m', 'src.server'],
                cwd: '/test/workspace',
            };
            (resolveLaunchConfig as jest.Mock).mockResolvedValue(launchConfig);

            const ctx = createMockContext();
            activate(ctx);
            await flushPromises();

            deactivate();

            // Calling deactivate again should not call dispose again
            mockStdioInstance.dispose.mockClear();
            deactivate();
            expect(mockStdioInstance.dispose).not.toHaveBeenCalled();
        });
    });

    // ──────────────────────────────────────────────────────────────────────
    // workspace detection
    // ──────────────────────────────────────────────────────────────────────

});

// ── Utility ─────────────────────────────────────────────────────────────────

/**
 * Flush all pending microtasks (resolved promises).
 */
function flushPromises(): Promise<void> {
    return new Promise((resolve) => setImmediate(resolve));
}
