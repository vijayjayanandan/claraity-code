/**
 * Comprehensive unit tests for DiffContentProvider and ClarAItySidebarProvider.
 *
 * Coverage:
 * - DiffContentProvider: setContent, provideTextDocumentContent, URI parsing, clear, dispose
 * - ClarAItySidebarProvider: construction, handleServerMessage routing, handleWebviewMessage
 *   routing (all message types), showSessionHistory, connection event forwarding
 *
 * Mock strategy:
 * - vscode module: mocked via __mocks__/vscode.js (configured in jest.config.js)
 * - StdioConnection: manually mocked with EventEmitter-based events and jest.fn() methods
 */

import * as vscode from 'vscode';
import { DiffContentProvider, ClarAItySidebarProvider } from '../sidebar-provider';
import type { ServerMessage, WebViewMessage } from '../types';

// ---------------------------------------------------------------------------
// Mock StdioConnection
// ---------------------------------------------------------------------------

/**
 * Creates a mock StdioConnection that mirrors the real class's public API:
 * - send(): jest.fn
 * - disconnect(): jest.fn
 * - isConnected: boolean (configurable)
 * - setApiKey / setTavilyKey / connect / updateUrl: jest.fn (StdioConnection-specific)
 * - onMessage / onConnected / onDisconnected: EventEmitter-backed events
 */
function createMockConnection() {
    const onMessageEmitter = new vscode.EventEmitter<ServerMessage>();
    const onConnectedEmitter = new vscode.EventEmitter<void>();
    const onDisconnectedEmitter = new vscode.EventEmitter<void>();

    const connection = {
        send: jest.fn(),
        disconnect: jest.fn(),
        isConnected: false,
        // StdioConnection-specific methods
        setApiKey: jest.fn(),
        setTavilyKey: jest.fn(),
        connect: jest.fn(),
        updateUrl: jest.fn(), // no-op stub for interface compat
        onMessage: onMessageEmitter.event,
        onConnected: onConnectedEmitter.event,
        onDisconnected: onDisconnectedEmitter.event,
        // Expose emitters for test control (not part of real API)
        _onMessageEmitter: onMessageEmitter,
        _onConnectedEmitter: onConnectedEmitter,
        _onDisconnectedEmitter: onDisconnectedEmitter,
        dispose() {
            onMessageEmitter.dispose();
            onConnectedEmitter.dispose();
            onDisconnectedEmitter.dispose();
        },
    };

    return connection;
}

type MockConnection = ReturnType<typeof createMockConnection>;

// ---------------------------------------------------------------------------
// Mock WebviewView for resolveWebviewView
// ---------------------------------------------------------------------------

function createMockWebviewView() {
    const messageEmitter = new vscode.EventEmitter<WebViewMessage>();
    const webview = {
        options: {} as any,
        html: '',
        onDidReceiveMessage: messageEmitter.event,
        postMessage: jest.fn().mockResolvedValue(true),
        asWebviewUri: jest.fn((uri: any) => uri),
        cspSource: 'mock-csp-source',
    };
    return {
        webview,
        _messageEmitter: messageEmitter,
    };
}

// ---------------------------------------------------------------------------
// DiffContentProvider Tests
// ---------------------------------------------------------------------------

describe('DiffContentProvider', () => {
    let provider: DiffContentProvider;

    beforeEach(() => {
        provider = new DiffContentProvider();
    });

    afterEach(() => {
        provider.dispose();
    });

    describe('setContent and provideTextDocumentContent', () => {
        test('stores and retrieves original content by callId', () => {
            provider.setContent('call-1', 'original', 'original text here');
            const uri = vscode.Uri.parse('claraity-diff:/call-1/original');
            const result = provider.provideTextDocumentContent(uri);
            expect(result).toBe('original text here');
        });

        test('stores and retrieves modified content by callId', () => {
            provider.setContent('call-1', 'modified', 'modified text here');
            const uri = vscode.Uri.parse('claraity-diff:/call-1/modified');
            const result = provider.provideTextDocumentContent(uri);
            expect(result).toBe('modified text here');
        });

        test('stores both original and modified independently', () => {
            provider.setContent('call-2', 'original', 'before');
            provider.setContent('call-2', 'modified', 'after');

            const origUri = vscode.Uri.parse('claraity-diff:/call-2/original');
            const modUri = vscode.Uri.parse('claraity-diff:/call-2/modified');

            expect(provider.provideTextDocumentContent(origUri)).toBe('before');
            expect(provider.provideTextDocumentContent(modUri)).toBe('after');
        });

        test('overwrites content when setContent is called again for the same key', () => {
            provider.setContent('call-3', 'original', 'first');
            provider.setContent('call-3', 'original', 'second');

            const uri = vscode.Uri.parse('claraity-diff:/call-3/original');
            expect(provider.provideTextDocumentContent(uri)).toBe('second');
        });

        test('handles multiple call IDs independently', () => {
            provider.setContent('a', 'original', 'content-a');
            provider.setContent('b', 'original', 'content-b');

            const uriA = vscode.Uri.parse('claraity-diff:/a/original');
            const uriB = vscode.Uri.parse('claraity-diff:/b/original');

            expect(provider.provideTextDocumentContent(uriA)).toBe('content-a');
            expect(provider.provideTextDocumentContent(uriB)).toBe('content-b');
        });
    });

    describe('URI path parsing', () => {
        test('handles URI path with leading slash', () => {
            provider.setContent('x', 'modified', 'has-slash');
            // Uri.parse produces path with leading /
            const uri = vscode.Uri.parse('claraity-diff:/x/modified');
            expect(provider.provideTextDocumentContent(uri)).toBe('has-slash');
        });

        test('handles URI path without leading slash', () => {
            provider.setContent('y', 'original', 'no-slash');
            // Construct a URI-like object with no leading slash in path
            const uri = { path: 'y/original' } as vscode.Uri;
            expect(provider.provideTextDocumentContent(uri)).toBe('no-slash');
        });

        test('handles URI with query parameters (label)', () => {
            provider.setContent('z', 'modified', 'with-query');
            // The real URI has ?label=... but provideTextDocumentContent only reads uri.path
            // Our vscode mock's Uri.parse splits query from path
            const uri = vscode.Uri.parse('claraity-diff:/z/modified?label=test.py');
            expect(provider.provideTextDocumentContent(uri)).toBe('with-query');
        });
    });

    describe('returns empty string for unknown key', () => {
        test('returns empty string when no content has been set', () => {
            const uri = vscode.Uri.parse('claraity-diff:/nonexistent/original');
            expect(provider.provideTextDocumentContent(uri)).toBe('');
        });

        test('returns empty string for unknown callId', () => {
            provider.setContent('known', 'original', 'exists');
            const uri = vscode.Uri.parse('claraity-diff:/unknown/original');
            expect(provider.provideTextDocumentContent(uri)).toBe('');
        });

        test('returns empty string for unknown side', () => {
            provider.setContent('known', 'original', 'exists');
            const uri = { path: 'known/bogus' } as vscode.Uri;
            expect(provider.provideTextDocumentContent(uri)).toBe('');
        });
    });

    describe('clear', () => {
        test('removes both original and modified for a callId', () => {
            provider.setContent('to-clear', 'original', 'orig');
            provider.setContent('to-clear', 'modified', 'mod');

            provider.clear('to-clear');

            const origUri = vscode.Uri.parse('claraity-diff:/to-clear/original');
            const modUri = vscode.Uri.parse('claraity-diff:/to-clear/modified');

            expect(provider.provideTextDocumentContent(origUri)).toBe('');
            expect(provider.provideTextDocumentContent(modUri)).toBe('');
        });

        test('does not affect other callIds', () => {
            provider.setContent('keep', 'original', 'keep-orig');
            provider.setContent('remove', 'original', 'remove-orig');

            provider.clear('remove');

            const keepUri = vscode.Uri.parse('claraity-diff:/keep/original');
            const removeUri = vscode.Uri.parse('claraity-diff:/remove/original');

            expect(provider.provideTextDocumentContent(keepUri)).toBe('keep-orig');
            expect(provider.provideTextDocumentContent(removeUri)).toBe('');
        });

        test('clearing a non-existent callId does not throw', () => {
            expect(() => provider.clear('does-not-exist')).not.toThrow();
        });
    });

    describe('dispose', () => {
        test('dispose does not throw', () => {
            expect(() => provider.dispose()).not.toThrow();
        });
    });
});


// ---------------------------------------------------------------------------
// ClarAItySidebarProvider Tests
// ---------------------------------------------------------------------------

describe('ClarAItySidebarProvider', () => {
    let connection: MockConnection;
    let provider: ClarAItySidebarProvider;
    let extensionUri: vscode.Uri;
    let log: vscode.OutputChannel;

    beforeEach(() => {
        connection = createMockConnection();
        extensionUri = vscode.Uri.file('/test/extension');
        log = vscode.window.createOutputChannel('test-log');
        provider = new ClarAItySidebarProvider(extensionUri, connection as any, log);
    });

    afterEach(() => {
        connection.dispose();
    });

    // Helper: resolve the webview view and return the mock + message sender
    function resolveView() {
        const mockView = createMockWebviewView();
        const context = {} as vscode.WebviewViewResolveContext;
        const token = { isCancellationRequested: false, onCancellationRequested: jest.fn() } as any;

        provider.resolveWebviewView(
            mockView as any,
            context,
            token,
        );

        return {
            webview: mockView.webview,
            sendMessage: (msg: WebViewMessage) => mockView._messageEmitter.fire(msg),
        };
    }

    // -----------------------------------------------------------------------
    // Construction
    // -----------------------------------------------------------------------

    describe('construction', () => {
        test('registers diff content provider for claraity-diff scheme', () => {
            expect(vscode.workspace.registerTextDocumentContentProvider).toHaveBeenCalledWith(
                'claraity-diff',
                expect.any(DiffContentProvider),
            );
        });

        test('subscribes to connection onMessage event', () => {
            // Verify the subscription works by firing a message and checking
            // that handleServerMessage is invoked (we can observe its side effect
            // after resolving the view)
            const { webview } = resolveView();

            const msg: ServerMessage = { type: 'stream_start' };
            connection._onMessageEmitter.fire(msg);

            expect(webview.postMessage).toHaveBeenCalledWith(
                expect.objectContaining({ type: 'serverMessage', payload: msg }),
            );
        });

        test('subscribes to connection onConnected event', () => {
            const { webview } = resolveView();

            connection._onConnectedEmitter.fire();

            expect(webview.postMessage).toHaveBeenCalledWith({
                type: 'connectionStatus',
                status: 'connected',
            });
        });

        test('subscribes to connection onDisconnected event', () => {
            const { webview } = resolveView();

            connection._onDisconnectedEmitter.fire();

            expect(webview.postMessage).toHaveBeenCalledWith({
                type: 'connectionStatus',
                status: 'disconnected',
            });
        });
    });

    // -----------------------------------------------------------------------
    // resolveWebviewView
    // -----------------------------------------------------------------------

    describe('resolveWebviewView', () => {
        test('sets webview options with enableScripts and localResourceRoots', () => {
            const { webview } = resolveView();

            expect(webview.options).toEqual({
                enableScripts: true,
                localResourceRoots: [extensionUri],
            });
        });

        test('sets webview html content', () => {
            const { webview } = resolveView();

            expect(typeof webview.html).toBe('string');
            expect(webview.html.length).toBeGreaterThan(0);
        });

        test('registers webview message handler', () => {
            const { webview, sendMessage } = resolveView();

            // Send a message and verify it routes to handleWebviewMessage
            sendMessage({ type: 'interrupt' });

            expect(connection.send).toHaveBeenCalledWith({ type: 'interrupt' });
        });
    });

    // -----------------------------------------------------------------------
    // handleServerMessage routing
    // -----------------------------------------------------------------------

    describe('handleServerMessage routing', () => {
        test('forwards all server messages to webview as serverMessage', () => {
            const { webview } = resolveView();

            const msg: ServerMessage = { type: 'text_delta', content: 'hello' };
            connection._onMessageEmitter.fire(msg);

            expect(webview.postMessage).toHaveBeenCalledWith({
                type: 'serverMessage',
                payload: msg,
            });
        });

        test('extracts session_info and posts sessionInfo to webview', () => {
            const { webview } = resolveView();

            const msg: ServerMessage = {
                type: 'session_info',
                session_id: 'sess-123',
                model_name: 'gpt-4',
                permission_mode: 'approve',
                working_directory: '/test',
                auto_approve_categories: { edit: true, execute: false, browser: false },
            };
            connection._onMessageEmitter.fire(msg);

            // Should have received both serverMessage AND sessionInfo
            expect(webview.postMessage).toHaveBeenCalledWith({
                type: 'serverMessage',
                payload: msg,
            });
            expect(webview.postMessage).toHaveBeenCalledWith({
                type: 'sessionInfo',
                sessionId: 'sess-123',
                model: 'gpt-4',
                permissionMode: 'approve',
                autoApproveCategories: { edit: true, execute: false, browser: false },
            });
        });

        test('routes sessions_list to webview as sessionsList', () => {
            const { webview } = resolveView();

            const sessions = [
                { session_id: 's1', first_message: 'Hello', message_count: 5, updated_at: '2026-01-01' },
            ];
            const msg: ServerMessage = { type: 'sessions_list', sessions };
            connection._onMessageEmitter.fire(msg);

            expect(webview.postMessage).toHaveBeenCalledWith({
                type: 'serverMessage',
                payload: msg,
            });
            expect(webview.postMessage).toHaveBeenCalledWith({
                type: 'sessionsList',
                sessions,
            });
        });

        test('routes session_history to webview as sessionHistory', () => {
            const { webview } = resolveView();

            const messages = [
                { role: 'user', content: 'hi' },
                { role: 'assistant', content: 'hello' },
            ];
            const msg: ServerMessage = { type: 'session_history', messages };
            connection._onMessageEmitter.fire(msg);

            expect(webview.postMessage).toHaveBeenCalledWith({
                type: 'serverMessage',
                payload: msg,
            });
            expect(webview.postMessage).toHaveBeenCalledWith({
                type: 'sessionHistory',
                messages,
            });
        });

        test('disconnects on non-recoverable error', () => {
            resolveView();

            const msg: ServerMessage = {
                type: 'error',
                error_type: 'fatal',
                user_message: 'Server crashed',
                recoverable: false,
            };
            connection._onMessageEmitter.fire(msg);

            expect(connection.disconnect).toHaveBeenCalledTimes(1);
        });

        test('does not disconnect on recoverable error', () => {
            resolveView();

            const msg: ServerMessage = {
                type: 'error',
                error_type: 'transient',
                user_message: 'Temporary issue',
                recoverable: true,
            };
            connection._onMessageEmitter.fire(msg);

            expect(connection.disconnect).not.toHaveBeenCalled();
        });

        test('does not disconnect on non-error messages', () => {
            resolveView();

            const msg: ServerMessage = { type: 'stream_start' };
            connection._onMessageEmitter.fire(msg);

            expect(connection.disconnect).not.toHaveBeenCalled();
        });

        test('handles server messages before view is resolved (no crash)', () => {
            // The view is not resolved yet, so postToWebview should silently no-op
            const msg: ServerMessage = { type: 'stream_start' };
            expect(() => connection._onMessageEmitter.fire(msg)).not.toThrow();
        });
    });

    // -----------------------------------------------------------------------
    // handleWebviewMessage routing
    // -----------------------------------------------------------------------

    describe('handleWebviewMessage routing', () => {
        test('chatMessage sends chat_message to server', () => {
            const { sendMessage } = resolveView();

            sendMessage({ type: 'chatMessage', content: 'Hello agent' });

            expect(connection.send).toHaveBeenCalledWith({
                type: 'chat_message',
                content: 'Hello agent',
            });
        });

        test('approvalResult sends approval_result with proper field mapping', () => {
            const { sendMessage } = resolveView();

            sendMessage({
                type: 'approvalResult',
                callId: 'call-42',
                approved: true,
                autoApproveFuture: true,
                feedback: 'looks good',
            });

            expect(connection.send).toHaveBeenCalledWith({
                type: 'approval_result',
                call_id: 'call-42',
                approved: true,
                auto_approve_future: true,
                feedback: 'looks good',
            });
        });

        test('approvalResult defaults autoApproveFuture to false and feedback to null', () => {
            const { sendMessage } = resolveView();

            sendMessage({
                type: 'approvalResult',
                callId: 'call-43',
                approved: false,
            });

            expect(connection.send).toHaveBeenCalledWith({
                type: 'approval_result',
                call_id: 'call-43',
                approved: false,
                auto_approve_future: false,
                feedback: null,
            });
        });

        test('interrupt sends interrupt to server', () => {
            const { sendMessage } = resolveView();

            sendMessage({ type: 'interrupt' });

            expect(connection.send).toHaveBeenCalledWith({ type: 'interrupt' });
        });

        test('ready sends connectionStatus connected when connection is connected', () => {
            const { webview, sendMessage } = resolveView();

            connection.isConnected = true;
            sendMessage({ type: 'ready' });

            expect(webview.postMessage).toHaveBeenCalledWith({
                type: 'connectionStatus',
                status: 'connected',
            });
        });

        test('ready does not send connectionStatus when connection is disconnected', () => {
            const { webview, sendMessage } = resolveView();

            connection.isConnected = false;
            webview.postMessage.mockClear();

            sendMessage({ type: 'ready' });

            expect(webview.postMessage).not.toHaveBeenCalledWith(
                expect.objectContaining({ type: 'connectionStatus' }),
            );
        });

        test('ready does not send anything to the server', () => {
            const { sendMessage } = resolveView();

            connection.isConnected = true;
            sendMessage({ type: 'ready' });

            expect(connection.send).not.toHaveBeenCalled();
        });

        test('copyToClipboard calls vscode.env.clipboard.writeText', () => {
            const { sendMessage } = resolveView();

            sendMessage({ type: 'copyToClipboard', text: 'copied text' });

            expect(vscode.env.clipboard.writeText).toHaveBeenCalledWith('copied text');
        });

        test('pauseResult sends pause_result with proper field mapping', () => {
            const { sendMessage } = resolveView();

            sendMessage({
                type: 'pauseResult',
                continueWork: true,
                feedback: 'keep going',
            });

            expect(connection.send).toHaveBeenCalledWith({
                type: 'pause_result',
                continue_work: true,
                feedback: 'keep going',
            });
        });

        test('pauseResult defaults feedback to null', () => {
            const { sendMessage } = resolveView();

            sendMessage({
                type: 'pauseResult',
                continueWork: false,
            });

            expect(connection.send).toHaveBeenCalledWith({
                type: 'pause_result',
                continue_work: false,
                feedback: null,
            });
        });

        test('clarifyResult sends clarify_result with proper field mapping', () => {
            const { sendMessage } = resolveView();

            sendMessage({
                type: 'clarifyResult',
                callId: 'call-99',
                submitted: true,
                responses: { q1: 'answer1', q2: 'answer2' },
            });

            expect(connection.send).toHaveBeenCalledWith({
                type: 'clarify_result',
                call_id: 'call-99',
                submitted: true,
                responses: { q1: 'answer1', q2: 'answer2' },
                chat_instead: false,
                chat_message: null,
            });
        });

        test('clarifyResult with null responses', () => {
            const { sendMessage } = resolveView();

            sendMessage({
                type: 'clarifyResult',
                callId: 'call-100',
                submitted: false,
                responses: null,
            });

            expect(connection.send).toHaveBeenCalledWith({
                type: 'clarify_result',
                call_id: 'call-100',
                submitted: false,
                responses: null,
                chat_instead: false,
                chat_message: null,
            });
        });

        test('planApprovalResult sends plan_approval_result with proper field mapping', () => {
            const { sendMessage } = resolveView();

            sendMessage({
                type: 'planApprovalResult',
                planHash: 'abc123',
                approved: true,
                autoAcceptEdits: true,
                feedback: 'approved the plan',
            });

            expect(connection.send).toHaveBeenCalledWith({
                type: 'plan_approval_result',
                plan_hash: 'abc123',
                approved: true,
                auto_accept_edits: true,
                feedback: 'approved the plan',
            });
        });

        test('planApprovalResult defaults autoAcceptEdits to false and feedback to null', () => {
            const { sendMessage } = resolveView();

            sendMessage({
                type: 'planApprovalResult',
                planHash: 'def456',
                approved: false,
            });

            expect(connection.send).toHaveBeenCalledWith({
                type: 'plan_approval_result',
                plan_hash: 'def456',
                approved: false,
                auto_accept_edits: false,
                feedback: null,
            });
        });

        test('setMode sends set_mode to server', () => {
            const { sendMessage } = resolveView();

            sendMessage({ type: 'setMode', mode: 'plan' });

            expect(connection.send).toHaveBeenCalledWith({
                type: 'set_mode',
                mode: 'plan',
            });
        });

        test('getConfig sends get_config to server', () => {
            const { sendMessage } = resolveView();

            sendMessage({ type: 'getConfig' });

            expect(connection.send).toHaveBeenCalledWith({ type: 'get_config' });
        });

        test('saveConfig sends save_config with config object to server', () => {
            const { sendMessage } = resolveView();

            const config = { model: 'gpt-4', temperature: 0.7 };
            sendMessage({ type: 'saveConfig', config });

            expect(connection.send).toHaveBeenCalledWith(
                expect.objectContaining({
                    type: 'save_config',
                    config,
                }),
            );
        });

        test('listModels sends list_models with backend details to server', () => {
            const { sendMessage } = resolveView();

            sendMessage({
                type: 'listModels',
                backend: 'openai',
                base_url: 'https://api.openai.com',
                api_key: 'sk-test',
            });

            expect(connection.send).toHaveBeenCalledWith(
                expect.objectContaining({
                    type: 'list_models',
                    backend: 'openai',
                    base_url: 'https://api.openai.com',
                    api_key: 'sk-test',
                }),
            );
        });

        test('setAutoApprove sends set_auto_approve with categories to server', () => {
            const { sendMessage } = resolveView();

            const categories = { edit: true, execute: false, browser: true };
            sendMessage({ type: 'setAutoApprove', categories });

            expect(connection.send).toHaveBeenCalledWith(
                expect.objectContaining({
                    type: 'set_auto_approve',
                    categories,
                }),
            );
        });

        test('getAutoApprove sends get_auto_approve to server', () => {
            const { sendMessage } = resolveView();

            sendMessage({ type: 'getAutoApprove' });

            expect(connection.send).toHaveBeenCalledWith(
                expect.objectContaining({ type: 'get_auto_approve' }),
            );
        });

        test('newSession sends new_session to server', () => {
            const { sendMessage } = resolveView();

            sendMessage({ type: 'newSession' });

            expect(connection.send).toHaveBeenCalledWith({ type: 'new_session' });
        });

        test('listSessions sends list_sessions to server', () => {
            const { sendMessage } = resolveView();

            sendMessage({ type: 'listSessions' });

            expect(connection.send).toHaveBeenCalledWith(
                expect.objectContaining({ type: 'list_sessions' }),
            );
        });

        test('resumeSession sends resume_session with session_id to server', () => {
            const { sendMessage } = resolveView();

            sendMessage({ type: 'resumeSession', sessionId: 'sess-abc' });

            expect(connection.send).toHaveBeenCalledWith(
                expect.objectContaining({
                    type: 'resume_session',
                    session_id: 'sess-abc',
                }),
            );
        });
    });

    // -----------------------------------------------------------------------
    // showSessionHistory
    // -----------------------------------------------------------------------

    describe('showSessionHistory', () => {
        test('posts showSessionHistory message to webview', () => {
            const { webview } = resolveView();

            provider.showSessionHistory();

            expect(webview.postMessage).toHaveBeenCalledWith({
                type: 'showSessionHistory',
            });
        });

        test('does not throw when view is not resolved', () => {
            // provider.view is undefined -- showSessionHistory should not crash
            expect(() => provider.showSessionHistory()).not.toThrow();
        });
    });

    // -----------------------------------------------------------------------
    // Connection event forwarding (before view resolved)
    // -----------------------------------------------------------------------

    describe('connection events before view resolved', () => {
        test('onConnected before resolveWebviewView does not throw', () => {
            expect(() => connection._onConnectedEmitter.fire()).not.toThrow();
        });

        test('onDisconnected before resolveWebviewView does not throw', () => {
            expect(() => connection._onDisconnectedEmitter.fire()).not.toThrow();
        });

        test('onMessage before resolveWebviewView does not throw', () => {
            const msg: ServerMessage = { type: 'stream_start' };
            expect(() => connection._onMessageEmitter.fire(msg)).not.toThrow();
        });
    });

    // -----------------------------------------------------------------------
    // Edge cases and integration scenarios
    // -----------------------------------------------------------------------

    describe('edge cases', () => {
        test('multiple server messages are all forwarded', () => {
            const { webview } = resolveView();

            const messages: ServerMessage[] = [
                { type: 'stream_start' },
                { type: 'text_delta', content: 'chunk1' },
                { type: 'text_delta', content: 'chunk2' },
                { type: 'stream_end' },
            ];

            for (const msg of messages) {
                connection._onMessageEmitter.fire(msg);
            }

            // Each message produces at least one postMessage call (serverMessage)
            expect(webview.postMessage).toHaveBeenCalledTimes(messages.length);
            for (const msg of messages) {
                expect(webview.postMessage).toHaveBeenCalledWith({
                    type: 'serverMessage',
                    payload: msg,
                });
            }
        });

        test('session_info message produces two postMessage calls', () => {
            const { webview } = resolveView();

            const msg: ServerMessage = {
                type: 'session_info',
                session_id: 's1',
                model_name: 'model',
                permission_mode: 'auto',
                working_directory: '/work',
            };
            connection._onMessageEmitter.fire(msg);

            // serverMessage + sessionInfo = 2 calls
            expect(webview.postMessage).toHaveBeenCalledTimes(2);
        });

        test('sessions_list message produces two postMessage calls', () => {
            const { webview } = resolveView();

            const msg: ServerMessage = { type: 'sessions_list', sessions: [] };
            connection._onMessageEmitter.fire(msg);

            // serverMessage + sessionsList = 2 calls
            expect(webview.postMessage).toHaveBeenCalledTimes(2);
        });

        test('session_history message produces two postMessage calls', () => {
            const { webview } = resolveView();

            const msg: ServerMessage = { type: 'session_history', messages: [] };
            connection._onMessageEmitter.fire(msg);

            // serverMessage + sessionHistory = 2 calls
            expect(webview.postMessage).toHaveBeenCalledTimes(2);
        });

        test('error with recoverable=false produces serverMessage + disconnect', () => {
            const { webview } = resolveView();

            const msg: ServerMessage = {
                type: 'error',
                error_type: 'fatal',
                user_message: 'Unrecoverable',
                recoverable: false,
            };
            connection._onMessageEmitter.fire(msg);

            // serverMessage forwarded
            expect(webview.postMessage).toHaveBeenCalledWith({
                type: 'serverMessage',
                payload: msg,
            });
            // connection disconnected
            expect(connection.disconnect).toHaveBeenCalledTimes(1);
        });

        test('chatMessage with empty content still sends', () => {
            const { sendMessage } = resolveView();

            sendMessage({ type: 'chatMessage', content: '' });

            expect(connection.send).toHaveBeenCalledWith({
                type: 'chat_message',
                content: '',
            });
        });

        test('copyToClipboard with empty string', () => {
            const { sendMessage } = resolveView();

            sendMessage({ type: 'copyToClipboard', text: '' });

            expect(vscode.env.clipboard.writeText).toHaveBeenCalledWith('');
        });

        test('approvalResult with rejected and feedback', () => {
            const { sendMessage } = resolveView();

            sendMessage({
                type: 'approvalResult',
                callId: 'call-reject',
                approved: false,
                feedback: 'too risky',
            });

            expect(connection.send).toHaveBeenCalledWith({
                type: 'approval_result',
                call_id: 'call-reject',
                approved: false,
                auto_approve_future: false,
                feedback: 'too risky',
            });
        });
    });
});
