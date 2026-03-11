/**
 * Comprehensive unit tests for extension.ts (activate / deactivate).
 *
 * Coverage:
 * - activate(): output channel, AgentConnection, SidebarProvider, webview
 *   registration, commands, status bar, connection event handlers,
 *   config change watcher, serverAutoStart scenarios, cleanup disposable
 * - deactivate(): disposes connection and server manager
 * - extractPort(): tested indirectly through ServerManager constructor args
 *
 * Total: 30+ tests covering all code paths in extension.ts
 */

import * as vscode from 'vscode';
import { activate, deactivate } from '../extension';

// ── Module mocks ────────────────────────────────────────────────────────────

jest.mock('../agent-connection');
jest.mock('../sidebar-provider');
jest.mock('../server-manager');
jest.mock('../python-env');

import { AgentConnection } from '../agent-connection';
import { ClarAItySidebarProvider } from '../sidebar-provider';
import { ServerManager } from '../server-manager';
import { resolveLaunchConfig } from '../python-env';

// ── Types for mock instances ────────────────────────────────────────────────

interface MockAgentConnection {
    connect: jest.Mock;
    send: jest.Mock;
    dispose: jest.Mock;
    updateUrl: jest.Mock;
    setAuthToken: jest.Mock;
    onConnected: jest.Mock;
    onDisconnected: jest.Mock;
    onMessage: jest.Mock;
    isConnected: boolean;
    authToken: string | null;
}

interface MockSidebarProvider {
    showSessionHistory: jest.Mock;
}

interface MockServerManager {
    start: jest.Mock;
    dispose: jest.Mock;
    onReady: jest.Mock;
    onStopped: jest.Mock;
    authToken: string | null;
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
        secrets: { get: jest.fn(), store: jest.fn(), delete: jest.fn(), onDidChange: jest.fn() } as any,
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
 * Stored callback registrations from mock event methods, keyed by event name.
 * Allows tests to fire events (connected, disconnected, onReady, onStopped)
 * after activate() has registered its listeners.
 */
let connectionCallbacks: Record<string, Function>;
let serverManagerCallbacks: Record<string, Function>;
let mockConnectionInstance: MockAgentConnection;
let mockSidebarInstance: MockSidebarProvider;
let mockServerManagerInstance: MockServerManager;

/**
 * Set up fresh mock constructors before each test.
 */
function setupMocks() {
    connectionCallbacks = {};
    serverManagerCallbacks = {};

    mockConnectionInstance = {
        connect: jest.fn(),
        send: jest.fn(),
        dispose: jest.fn(),
        updateUrl: jest.fn(),
        setAuthToken: jest.fn(),
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
        authToken: null,
    };

    mockSidebarInstance = {
        showSessionHistory: jest.fn(),
    };

    mockServerManagerInstance = {
        start: jest.fn(),
        dispose: jest.fn(),
        onReady: jest.fn((cb: Function) => {
            serverManagerCallbacks['ready'] = cb;
            return { dispose: jest.fn() };
        }),
        onStopped: jest.fn((cb: Function) => {
            serverManagerCallbacks['stopped'] = cb;
            return { dispose: jest.fn() };
        }),
        authToken: null,
    };

    (AgentConnection as jest.Mock).mockImplementation(() => mockConnectionInstance);
    (ClarAItySidebarProvider as jest.Mock).mockImplementation(() => mockSidebarInstance);
    (ServerManager as jest.Mock).mockImplementation(() => mockServerManagerInstance);
    (resolveLaunchConfig as jest.Mock).mockResolvedValue(null);
}

/**
 * Configure the vscode.workspace.getConfiguration mock to return specific
 * values. Unspecified keys fall back to their defaults.
 */
function setConfig(overrides: Record<string, any>) {
    (vscode.workspace.getConfiguration as jest.Mock).mockImplementation(() => ({
        get: jest.fn((key: string, defaultValue?: any) => {
            return overrides[key] !== undefined ? overrides[key] : defaultValue;
        }),
        update: jest.fn().mockResolvedValue(undefined),
        has: jest.fn((key: string) => key in overrides),
        inspect: jest.fn(() => undefined),
    }));
}

/**
 * Set workspace folders. Pass null to simulate no workspace.
 */
function setWorkspaceFolders(folders: any[] | undefined) {
    (vscode.workspace as any).workspaceFolders = folders;
}

// ── Test suite ──────────────────────────────────────────────────────────────

describe('extension.ts', () => {
    beforeEach(() => {
        jest.clearAllMocks();
        setupMocks();
        // Default: workspace folder exists, serverAutoStart defaults on
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
                setConfig({ serverAutoStart: false, autoConnect: false });
                activate(ctx);

                expect(vscode.window.createOutputChannel).toHaveBeenCalledWith(
                    'ClarAIty Extension',
                );
            });

            test('pushes output channel into subscriptions', () => {
                const ctx = createMockContext();
                setConfig({ serverAutoStart: false, autoConnect: false });
                activate(ctx);

                // The output channel is the first subscription pushed
                const channel = (vscode.window.createOutputChannel as jest.Mock).mock.results[0].value;
                expect(ctx.subscriptions).toContain(channel);
            });

            test('logs activation messages', () => {
                const ctx = createMockContext();
                setConfig({ serverAutoStart: false, autoConnect: false });
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

        describe('AgentConnection', () => {
            test('creates AgentConnection with default serverUrl from config', () => {
                const ctx = createMockContext();
                setConfig({ serverAutoStart: false, autoConnect: false });
                activate(ctx);

                expect(AgentConnection).toHaveBeenCalledWith(
                    'ws://localhost:9120/ws',
                    expect.anything(), // output channel
                );
            });

            test('creates AgentConnection with custom serverUrl from config', () => {
                const ctx = createMockContext();
                setConfig({
                    serverUrl: 'ws://myhost:4567/ws',
                    serverAutoStart: false,
                    autoConnect: false,
                });
                activate(ctx);

                expect(AgentConnection).toHaveBeenCalledWith(
                    'ws://myhost:4567/ws',
                    expect.anything(),
                );
            });
        });

        describe('ClarAItySidebarProvider', () => {
            test('creates sidebar provider with extensionUri, connection, and log', () => {
                const ctx = createMockContext();
                setConfig({ serverAutoStart: false, autoConnect: false });
                activate(ctx);

                expect(ClarAItySidebarProvider).toHaveBeenCalledWith(
                    ctx.extensionUri,
                    mockConnectionInstance,
                    expect.anything(), // output channel
                );
            });
        });

        describe('webview registration', () => {
            test('registers webview view provider for "claraity.chatView"', () => {
                const ctx = createMockContext();
                setConfig({ serverAutoStart: false, autoConnect: false });
                activate(ctx);

                expect(vscode.window.registerWebviewViewProvider).toHaveBeenCalledWith(
                    'claraity.chatView',
                    mockSidebarInstance,
                );
            });

            test('pushes webview registration disposable into subscriptions', () => {
                const ctx = createMockContext();
                setConfig({ serverAutoStart: false, autoConnect: false });
                activate(ctx);

                // registerWebviewViewProvider returns a Disposable
                const disposable = (vscode.window.registerWebviewViewProvider as jest.Mock)
                    .mock.results[0].value;
                expect(ctx.subscriptions).toContain(disposable);
            });
        });

        describe('command registration', () => {
            test('registers "claraity.newChat" command', () => {
                const ctx = createMockContext();
                setConfig({ serverAutoStart: false, autoConnect: false });
                activate(ctx);

                expect(vscode.commands.registerCommand).toHaveBeenCalledWith(
                    'claraity.newChat',
                    expect.any(Function),
                );
            });

            test('registers "claraity.interrupt" command', () => {
                const ctx = createMockContext();
                setConfig({ serverAutoStart: false, autoConnect: false });
                activate(ctx);

                expect(vscode.commands.registerCommand).toHaveBeenCalledWith(
                    'claraity.interrupt',
                    expect.any(Function),
                );
            });

            test('registers "claraity.sessionHistory" command', () => {
                const ctx = createMockContext();
                setConfig({ serverAutoStart: false, autoConnect: false });
                activate(ctx);

                expect(vscode.commands.registerCommand).toHaveBeenCalledWith(
                    'claraity.sessionHistory',
                    expect.any(Function),
                );
            });

            test('newChat command focuses the chat view', () => {
                const ctx = createMockContext();
                setConfig({ serverAutoStart: false, autoConnect: false });
                activate(ctx);

                // Find the newChat callback
                const calls = (vscode.commands.registerCommand as jest.Mock).mock.calls;
                const newChatCall = calls.find(
                    (c: any[]) => c[0] === 'claraity.newChat',
                );
                expect(newChatCall).toBeDefined();

                // Invoke it
                newChatCall![1]();

                expect(vscode.commands.executeCommand).toHaveBeenCalledWith(
                    'claraity.chatView.focus',
                );
            });

            test('interrupt command sends interrupt message via connection', () => {
                const ctx = createMockContext();
                setConfig({ serverAutoStart: false, autoConnect: false });
                activate(ctx);

                const calls = (vscode.commands.registerCommand as jest.Mock).mock.calls;
                const interruptCall = calls.find(
                    (c: any[]) => c[0] === 'claraity.interrupt',
                );
                expect(interruptCall).toBeDefined();

                interruptCall![1]();

                expect(mockConnectionInstance.send).toHaveBeenCalledWith({
                    type: 'interrupt',
                });
            });

            test('sessionHistory command calls showSessionHistory on sidebar provider', () => {
                const ctx = createMockContext();
                setConfig({ serverAutoStart: false, autoConnect: false });
                activate(ctx);

                const calls = (vscode.commands.registerCommand as jest.Mock).mock.calls;
                const historyCall = calls.find(
                    (c: any[]) => c[0] === 'claraity.sessionHistory',
                );
                expect(historyCall).toBeDefined();

                historyCall![1]();

                expect(mockSidebarInstance.showSessionHistory).toHaveBeenCalled();
            });

            test('pushes all command disposables into subscriptions', () => {
                const ctx = createMockContext();
                setConfig({ serverAutoStart: false, autoConnect: false });
                activate(ctx);

                // registerCommand is called 11 times (newChat, interrupt, sessionHistory, acceptChange, rejectChange, viewDiff, undoTurn, explainCode, fixCode, refactorCode, addToChat)
                expect(vscode.commands.registerCommand).toHaveBeenCalledTimes(11);

                // Each returns a Disposable that should be in subscriptions
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
                setConfig({ serverAutoStart: false, autoConnect: false });
                activate(ctx);

                expect(vscode.window.createStatusBarItem).toHaveBeenCalledWith(
                    vscode.StatusBarAlignment.Left,
                    100,
                );
            });

            test('sets status bar command to claraity.newChat', () => {
                const ctx = createMockContext();
                setConfig({ serverAutoStart: false, autoConnect: false });
                activate(ctx);

                const statusBar = (vscode.window.createStatusBarItem as jest.Mock)
                    .mock.results[0].value;
                expect(statusBar.command).toBe('claraity.newChat');
            });

            test('shows the status bar', () => {
                const ctx = createMockContext();
                setConfig({ serverAutoStart: false, autoConnect: false });
                activate(ctx);

                const statusBar = (vscode.window.createStatusBarItem as jest.Mock)
                    .mock.results[0].value;
                expect(statusBar.show).toHaveBeenCalled();
            });

            test('pushes status bar into subscriptions', () => {
                const ctx = createMockContext();
                setConfig({ serverAutoStart: false, autoConnect: false });
                activate(ctx);

                const statusBar = (vscode.window.createStatusBarItem as jest.Mock)
                    .mock.results[0].value;
                expect(ctx.subscriptions).toContain(statusBar);
            });
        });

        describe('connection event handlers', () => {
            test('updates status bar text on connected event', () => {
                const ctx = createMockContext();
                setConfig({ serverAutoStart: false, autoConnect: false });
                activate(ctx);

                const statusBar = (vscode.window.createStatusBarItem as jest.Mock)
                    .mock.results[0].value;

                // Fire the connected callback
                expect(connectionCallbacks['connected']).toBeDefined();
                connectionCallbacks['connected']();

                expect(statusBar.text).toBe('$(sparkle) ClarAIty');
                expect(statusBar.tooltip).toBe('ClarAIty - Connected');
            });

            test('updates status bar text on disconnected event', () => {
                const ctx = createMockContext();
                setConfig({ serverAutoStart: false, autoConnect: false });
                activate(ctx);

                const statusBar = (vscode.window.createStatusBarItem as jest.Mock)
                    .mock.results[0].value;

                expect(connectionCallbacks['disconnected']).toBeDefined();
                connectionCallbacks['disconnected']();

                expect(statusBar.text).toBe('$(sparkle) ClarAIty (offline)');
                expect(statusBar.tooltip).toBe('ClarAIty - Disconnected');
            });

            test('registers both onConnected and onDisconnected', () => {
                const ctx = createMockContext();
                setConfig({ serverAutoStart: false, autoConnect: false });
                activate(ctx);

                expect(mockConnectionInstance.onConnected).toHaveBeenCalledTimes(1);
                expect(mockConnectionInstance.onDisconnected).toHaveBeenCalledTimes(1);
            });
        });

        describe('configuration change watcher', () => {
            test('registers onDidChangeConfiguration listener', () => {
                const ctx = createMockContext();
                setConfig({ serverAutoStart: false, autoConnect: false });
                activate(ctx);

                expect(vscode.workspace.onDidChangeConfiguration).toHaveBeenCalled();
            });

            test('pushes config change disposable into subscriptions', () => {
                const ctx = createMockContext();
                setConfig({ serverAutoStart: false, autoConnect: false });
                activate(ctx);

                const disposable = (vscode.workspace.onDidChangeConfiguration as jest.Mock)
                    .mock.results[0].value;
                expect(ctx.subscriptions).toContain(disposable);
            });

            test('updates connection URL when claraity.serverUrl config changes', () => {
                // Capture the config change callback
                let configChangeCallback: Function | undefined;
                (vscode.workspace.onDidChangeConfiguration as jest.Mock).mockImplementation(
                    (cb: Function) => {
                        configChangeCallback = cb;
                        return { dispose: jest.fn() };
                    },
                );

                const ctx = createMockContext();
                setConfig({ serverAutoStart: false, autoConnect: false });
                activate(ctx);

                expect(configChangeCallback).toBeDefined();

                // Set up what getConfiguration will return on the second call
                const newConfig = {
                    get: jest.fn((key: string, defaultValue?: any) => {
                        if (key === 'serverUrl') { return 'ws://newhost:8888/ws'; }
                        return defaultValue;
                    }),
                    update: jest.fn(),
                    has: jest.fn(),
                    inspect: jest.fn(),
                };
                (vscode.workspace.getConfiguration as jest.Mock).mockReturnValue(newConfig);

                // Simulate config change event
                configChangeCallback!({
                    affectsConfiguration: (section: string) => section === 'claraity.serverUrl',
                });

                expect(mockConnectionInstance.updateUrl).toHaveBeenCalledWith(
                    'ws://newhost:8888/ws',
                );
            });

            test('does not update URL when unrelated config changes', () => {
                let configChangeCallback: Function | undefined;
                (vscode.workspace.onDidChangeConfiguration as jest.Mock).mockImplementation(
                    (cb: Function) => {
                        configChangeCallback = cb;
                        return { dispose: jest.fn() };
                    },
                );

                const ctx = createMockContext();
                setConfig({ serverAutoStart: false, autoConnect: false });
                activate(ctx);

                // Simulate unrelated config change
                configChangeCallback!({
                    affectsConfiguration: (section: string) => section === 'editor.fontSize',
                });

                expect(mockConnectionInstance.updateUrl).not.toHaveBeenCalled();
            });
        });

        describe('cleanup disposable', () => {
            test('pushes a cleanup disposable that disposes connection', () => {
                const ctx = createMockContext();
                setConfig({ serverAutoStart: false, autoConnect: false });
                activate(ctx);

                // Find the cleanup disposable (has a dispose function that calls connection.dispose)
                const cleanupDisposables = ctx.subscriptions.filter(
                    (s: any) => typeof s.dispose === 'function' && s !== (vscode.window.createOutputChannel as jest.Mock).mock.results[0].value,
                );

                // There should be at least one cleanup disposable
                expect(cleanupDisposables.length).toBeGreaterThan(0);

                // Call dispose on the last one (the cleanup disposable added at the end)
                const lastDisposable = ctx.subscriptions[ctx.subscriptions.length - 1] as any;
                lastDisposable.dispose();

                expect(mockConnectionInstance.dispose).toHaveBeenCalled();
            });
        });
    });

    // ──────────────────────────────────────────────────────────────────────
    // activate() - serverAutoStart scenarios
    // ──────────────────────────────────────────────────────────────────────

    describe('activate() - serverAutoStart=true with workspace', () => {
        test('calls resolveLaunchConfig with correct arguments', () => {
            const ctx = createMockContext();
            setConfig({
                serverAutoStart: true,
                serverUrl: 'ws://localhost:9120/ws',
                pythonPath: '/usr/bin/python3',
                devMode: 'auto',
                autoInstallAgent: true,
            });
            activate(ctx);

            expect(resolveLaunchConfig).toHaveBeenCalledWith(
                '/usr/bin/python3',
                9120,
                '/test/workspace',
                'auto',
                true,
            );
        });

        test('sets status bar to checking state initially', () => {
            const ctx = createMockContext();
            setConfig({ serverAutoStart: true });
            activate(ctx);

            const statusBar = (vscode.window.createStatusBarItem as jest.Mock)
                .mock.results[0].value;
            expect(statusBar.text).toBe('$(loading~spin) ClarAIty (checking...)');
            expect(statusBar.tooltip).toBe('ClarAIty - Detecting environment...');
        });

        test('creates ServerManager with launch config and port when resolved', async () => {
            const launchConfig = {
                mode: 'dev' as const,
                command: 'python',
                args: ['-m', 'src.server', '--port', '9120'],
                cwd: '/test/workspace',
            };
            (resolveLaunchConfig as jest.Mock).mockResolvedValue(launchConfig);

            const ctx = createMockContext();
            setConfig({ serverAutoStart: true });
            activate(ctx);

            // Wait for the promise to resolve
            await flushPromises();

            expect(ServerManager).toHaveBeenCalledWith(launchConfig, 9120);
        });

        test('starts the server manager after creation', async () => {
            const launchConfig = {
                mode: 'installed' as const,
                command: 'python',
                args: ['--serve', '--port', '9120'],
                cwd: '/test/workspace',
            };
            (resolveLaunchConfig as jest.Mock).mockResolvedValue(launchConfig);

            const ctx = createMockContext();
            setConfig({ serverAutoStart: true });
            activate(ctx);

            await flushPromises();

            expect(mockServerManagerInstance.start).toHaveBeenCalled();
        });

        test('pushes server manager into subscriptions', async () => {
            const launchConfig = {
                mode: 'dev' as const,
                command: 'python',
                args: ['-m', 'src.server', '--port', '9120'],
                cwd: '/test/workspace',
            };
            (resolveLaunchConfig as jest.Mock).mockResolvedValue(launchConfig);

            const ctx = createMockContext();
            setConfig({ serverAutoStart: true });
            activate(ctx);

            await flushPromises();

            expect(ctx.subscriptions).toContain(mockServerManagerInstance);
        });

        test('connects WebSocket when server is ready', async () => {
            const launchConfig = {
                mode: 'dev' as const,
                command: 'python',
                args: ['-m', 'src.server', '--port', '9120'],
                cwd: '/test/workspace',
            };
            (resolveLaunchConfig as jest.Mock).mockResolvedValue(launchConfig);

            const ctx = createMockContext();
            setConfig({ serverAutoStart: true });
            activate(ctx);

            await flushPromises();

            // Fire the onReady callback
            expect(serverManagerCallbacks['ready']).toBeDefined();
            serverManagerCallbacks['ready']();

            expect(mockConnectionInstance.connect).toHaveBeenCalled();
        });

        test('sets auth token on connection when server provides one', async () => {
            const launchConfig = {
                mode: 'dev' as const,
                command: 'python',
                args: ['-m', 'src.server', '--port', '9120'],
                cwd: '/test/workspace',
            };
            (resolveLaunchConfig as jest.Mock).mockResolvedValue(launchConfig);

            const ctx = createMockContext();
            setConfig({ serverAutoStart: true });
            activate(ctx);

            await flushPromises();

            // Simulate server providing an auth token
            mockServerManagerInstance.authToken = 'secret-token-123';

            // Fire the onReady callback
            serverManagerCallbacks['ready']();

            expect(mockConnectionInstance.setAuthToken).toHaveBeenCalledWith(
                'secret-token-123',
            );
            expect(mockConnectionInstance.connect).toHaveBeenCalled();
        });

        test('does not set auth token if server has none', async () => {
            const launchConfig = {
                mode: 'dev' as const,
                command: 'python',
                args: ['-m', 'src.server', '--port', '9120'],
                cwd: '/test/workspace',
            };
            (resolveLaunchConfig as jest.Mock).mockResolvedValue(launchConfig);

            const ctx = createMockContext();
            setConfig({ serverAutoStart: true });
            activate(ctx);

            await flushPromises();

            // authToken is null by default
            mockServerManagerInstance.authToken = null;
            serverManagerCallbacks['ready']();

            expect(mockConnectionInstance.setAuthToken).not.toHaveBeenCalled();
            expect(mockConnectionInstance.connect).toHaveBeenCalled();
        });

        test('updates status bar to starting state after launch config resolves', async () => {
            const launchConfig = {
                mode: 'dev' as const,
                command: 'python',
                args: ['-m', 'src.server', '--port', '9120'],
                cwd: '/test/workspace',
            };
            (resolveLaunchConfig as jest.Mock).mockResolvedValue(launchConfig);

            const ctx = createMockContext();
            setConfig({ serverAutoStart: true });
            activate(ctx);

            await flushPromises();

            const statusBar = (vscode.window.createStatusBarItem as jest.Mock)
                .mock.results[0].value;
            expect(statusBar.text).toBe('$(loading~spin) ClarAIty (starting...)');
            expect(statusBar.tooltip).toContain('Starting server');
            expect(statusBar.tooltip).toContain('dev mode');
        });

        test('updates status bar on server stopped event', async () => {
            const launchConfig = {
                mode: 'dev' as const,
                command: 'python',
                args: ['-m', 'src.server', '--port', '9120'],
                cwd: '/test/workspace',
            };
            (resolveLaunchConfig as jest.Mock).mockResolvedValue(launchConfig);

            const ctx = createMockContext();
            setConfig({ serverAutoStart: true });
            activate(ctx);

            await flushPromises();

            // Fire the onStopped callback with a reason
            serverManagerCallbacks['stopped']('Process crashed');

            const statusBar = (vscode.window.createStatusBarItem as jest.Mock)
                .mock.results[0].value;
            expect(statusBar.text).toBe('$(error) ClarAIty (server error)');
            expect(statusBar.tooltip).toBe('ClarAIty - Server stopped: Process crashed');
        });

        test('shows not-installed status when resolveLaunchConfig returns null', async () => {
            (resolveLaunchConfig as jest.Mock).mockResolvedValue(null);

            const ctx = createMockContext();
            setConfig({ serverAutoStart: true });
            activate(ctx);

            await flushPromises();

            const statusBar = (vscode.window.createStatusBarItem as jest.Mock)
                .mock.results[0].value;
            expect(statusBar.text).toBe('$(error) ClarAIty (not installed)');
            expect(statusBar.tooltip).toBe('ClarAIty - Agent not found');
        });

        test('does not create ServerManager when resolveLaunchConfig returns null', async () => {
            (resolveLaunchConfig as jest.Mock).mockResolvedValue(null);

            const ctx = createMockContext();
            setConfig({ serverAutoStart: true });
            activate(ctx);

            await flushPromises();

            expect(ServerManager).not.toHaveBeenCalled();
        });

        test('handles resolveLaunchConfig rejection gracefully', async () => {
            (resolveLaunchConfig as jest.Mock).mockRejectedValue(
                new Error('Python not found'),
            );

            const ctx = createMockContext();
            setConfig({ serverAutoStart: true });
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
            setConfig({ serverAutoStart: true });
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
            setConfig({ serverAutoStart: true });
            activate(ctx);

            await flushPromises();

            const channel = (vscode.window.createOutputChannel as jest.Mock)
                .mock.results[0].value;
            expect(channel.appendLine).toHaveBeenCalledWith(
                '[ERROR] Environment resolution failed: Unexpected failure',
            );
        });
    });

    describe('activate() - serverAutoStart=true without workspace', () => {
        test('shows warning message when no workspace folder', () => {
            setWorkspaceFolders(undefined);
            const ctx = createMockContext();
            setConfig({ serverAutoStart: true });
            activate(ctx);

            expect(vscode.window.showWarningMessage).toHaveBeenCalledWith(
                'ClarAIty: No workspace folder open. Cannot auto-start server.',
            );
        });

        test('sets status bar to offline when no workspace folder', () => {
            setWorkspaceFolders(undefined);
            const ctx = createMockContext();
            setConfig({ serverAutoStart: true });
            activate(ctx);

            const statusBar = (vscode.window.createStatusBarItem as jest.Mock)
                .mock.results[0].value;
            expect(statusBar.text).toBe('$(sparkle) ClarAIty (offline)');
            expect(statusBar.tooltip).toBe('ClarAIty - No workspace folder');
        });

        test('connects directly if autoConnect is true and no workspace', () => {
            setWorkspaceFolders(undefined);
            const ctx = createMockContext();
            setConfig({ serverAutoStart: true, autoConnect: true });
            activate(ctx);

            expect(mockConnectionInstance.connect).toHaveBeenCalled();
        });

        test('does not connect if autoConnect is false and no workspace', () => {
            setWorkspaceFolders(undefined);
            const ctx = createMockContext();
            setConfig({ serverAutoStart: true, autoConnect: false });
            activate(ctx);

            expect(mockConnectionInstance.connect).not.toHaveBeenCalled();
        });

        test('does not call resolveLaunchConfig when no workspace', () => {
            setWorkspaceFolders(undefined);
            const ctx = createMockContext();
            setConfig({ serverAutoStart: true });
            activate(ctx);

            expect(resolveLaunchConfig).not.toHaveBeenCalled();
        });

        test('handles empty workspace folders array', () => {
            setWorkspaceFolders([]);
            const ctx = createMockContext();
            setConfig({ serverAutoStart: true });
            activate(ctx);

            expect(vscode.window.showWarningMessage).toHaveBeenCalledWith(
                'ClarAIty: No workspace folder open. Cannot auto-start server.',
            );
        });
    });

    describe('activate() - serverAutoStart=false', () => {
        test('sets status bar text when serverAutoStart is false', () => {
            const ctx = createMockContext();
            setConfig({ serverAutoStart: false, autoConnect: false });
            activate(ctx);

            const statusBar = (vscode.window.createStatusBarItem as jest.Mock)
                .mock.results[0].value;
            expect(statusBar.text).toBe('$(sparkle) ClarAIty');
            expect(statusBar.tooltip).toBe('Open ClarAIty Chat');
        });

        test('connects automatically when autoConnect is true', () => {
            const ctx = createMockContext();
            setConfig({ serverAutoStart: false, autoConnect: true });
            activate(ctx);

            expect(mockConnectionInstance.connect).toHaveBeenCalled();
        });

        test('does not connect when autoConnect is false', () => {
            const ctx = createMockContext();
            setConfig({ serverAutoStart: false, autoConnect: false });
            activate(ctx);

            expect(mockConnectionInstance.connect).not.toHaveBeenCalled();
        });

        test('does not call resolveLaunchConfig', () => {
            const ctx = createMockContext();
            setConfig({ serverAutoStart: false });
            activate(ctx);

            expect(resolveLaunchConfig).not.toHaveBeenCalled();
        });

        test('does not create ServerManager', () => {
            const ctx = createMockContext();
            setConfig({ serverAutoStart: false });
            activate(ctx);

            expect(ServerManager).not.toHaveBeenCalled();
        });
    });

    // ──────────────────────────────────────────────────────────────────────
    // activate() - extractPort (tested indirectly)
    // ──────────────────────────────────────────────────────────────────────

    describe('activate() - port extraction', () => {
        test('extracts port 9120 from default URL', async () => {
            const launchConfig = {
                mode: 'dev' as const,
                command: 'python',
                args: [],
                cwd: '/test',
            };
            (resolveLaunchConfig as jest.Mock).mockResolvedValue(launchConfig);

            const ctx = createMockContext();
            setConfig({ serverAutoStart: true, serverUrl: 'ws://localhost:9120/ws' });
            activate(ctx);

            await flushPromises();

            // Port is passed as second arg to ServerManager constructor
            expect(ServerManager).toHaveBeenCalledWith(launchConfig, 9120);
        });

        test('extracts custom port from URL', async () => {
            const launchConfig = {
                mode: 'dev' as const,
                command: 'python',
                args: [],
                cwd: '/test',
            };
            (resolveLaunchConfig as jest.Mock).mockResolvedValue(launchConfig);

            const ctx = createMockContext();
            setConfig({ serverAutoStart: true, serverUrl: 'ws://example.com:4567/ws' });
            activate(ctx);

            await flushPromises();

            expect(ServerManager).toHaveBeenCalledWith(launchConfig, 4567);
        });

        test('extracts port from wss:// URL', async () => {
            const launchConfig = {
                mode: 'dev' as const,
                command: 'python',
                args: [],
                cwd: '/test',
            };
            (resolveLaunchConfig as jest.Mock).mockResolvedValue(launchConfig);

            const ctx = createMockContext();
            setConfig({ serverAutoStart: true, serverUrl: 'wss://secure.host:8443/ws' });
            activate(ctx);

            await flushPromises();

            expect(ServerManager).toHaveBeenCalledWith(launchConfig, 8443);
        });

        test('falls back to port 9120 for unparseable URL', async () => {
            const launchConfig = {
                mode: 'dev' as const,
                command: 'python',
                args: [],
                cwd: '/test',
            };
            (resolveLaunchConfig as jest.Mock).mockResolvedValue(launchConfig);

            const ctx = createMockContext();
            setConfig({ serverAutoStart: true, serverUrl: 'not-a-url' });
            activate(ctx);

            await flushPromises();

            // Port is also passed to resolveLaunchConfig (second arg)
            expect(resolveLaunchConfig).toHaveBeenCalledWith(
                expect.anything(),
                9120,
                expect.anything(),
                expect.anything(),
                expect.anything(),
            );
        });

        test('falls back to port 9120 when URL has no explicit port', async () => {
            const launchConfig = {
                mode: 'dev' as const,
                command: 'python',
                args: [],
                cwd: '/test',
            };
            (resolveLaunchConfig as jest.Mock).mockResolvedValue(launchConfig);

            const ctx = createMockContext();
            // ws://localhost/ws has no port -> URL.port is empty string
            setConfig({ serverAutoStart: true, serverUrl: 'ws://localhost/ws' });
            activate(ctx);

            await flushPromises();

            expect(ServerManager).toHaveBeenCalledWith(launchConfig, 9120);
        });
    });

    // ──────────────────────────────────────────────────────────────────────
    // deactivate()
    // ──────────────────────────────────────────────────────────────────────

    describe('deactivate()', () => {
        test('disposes connection when active', () => {
            const ctx = createMockContext();
            setConfig({ serverAutoStart: false, autoConnect: false });
            activate(ctx);

            deactivate();

            expect(mockConnectionInstance.dispose).toHaveBeenCalled();
        });

        test('disposes server manager when active', async () => {
            const launchConfig = {
                mode: 'dev' as const,
                command: 'python',
                args: [],
                cwd: '/test',
            };
            (resolveLaunchConfig as jest.Mock).mockResolvedValue(launchConfig);

            const ctx = createMockContext();
            setConfig({ serverAutoStart: true });
            activate(ctx);

            await flushPromises();

            deactivate();

            expect(mockServerManagerInstance.dispose).toHaveBeenCalled();
        });

        test('does not throw when called without prior activation', () => {
            // Reset module-level state by deactivating first
            deactivate();
            // Calling again should not throw
            expect(() => deactivate()).not.toThrow();
        });

        test('does not dispose server manager when serverAutoStart was false', () => {
            // First clear any prior state
            deactivate();

            const ctx = createMockContext();
            setConfig({ serverAutoStart: false, autoConnect: false });
            activate(ctx);

            // Reset mock call count after activate
            mockServerManagerInstance.dispose.mockClear();

            deactivate();

            // ServerManager was never created, so dispose should not be called
            // (the mock instance exists but ServerManager constructor was not called)
            expect(ServerManager).not.toHaveBeenCalled();
        });
    });

    // ──────────────────────────────────────────────────────────────────────
    // activate() - multiple activations (module-level state)
    // ──────────────────────────────────────────────────────────────────────

    describe('activate() - module-level state', () => {
        test('replaces previous connection on re-activation', () => {
            // First activation
            const ctx1 = createMockContext();
            setConfig({ serverAutoStart: false, autoConnect: false });
            activate(ctx1);

            const firstConnection = mockConnectionInstance;

            // Reset mocks and create new instances for second activation
            setupMocks();

            const ctx2 = createMockContext();
            setConfig({ serverAutoStart: false, autoConnect: false });
            activate(ctx2);

            // deactivate should dispose the second connection, not the first
            deactivate();
            expect(mockConnectionInstance.dispose).toHaveBeenCalled();
        });
    });
});

// ── Utility ─────────────────────────────────────────────────────────────────

/**
 * Flush all pending microtasks (resolved promises).
 */
function flushPromises(): Promise<void> {
    return new Promise((resolve) => setImmediate(resolve));
}
