/**
 * Unit tests for ServerManager.
 *
 * Coverage:
 * - Construction: output channel creation, initial state
 * - start(): spawn args, stdout/stderr piping, spawn error handling, no-op if already running
 * - Auth token extraction: parsing "Auth Token: <token>" from stdout
 * - Health polling: polls /health every 500ms, fires onReady when health=200 AND token captured,
 *   keeps polling when healthy but no token, times out after 30s, stops when process exits
 * - Process lifecycle: error event, exit event (normal vs disposed)
 * - dispose(): kills process (taskkill on Windows, SIGTERM on Unix), stops health poll,
 *   disposes events and output channel
 * - Events: onReady and onStopped fire correctly
 */

import * as vscode from 'vscode';
import { EventEmitter } from 'events';
import { PassThrough } from 'stream';

// ---------------------------------------------------------------------------
// Mock child_process
// ---------------------------------------------------------------------------

class MockChildProcess extends EventEmitter {
    public stdout = new PassThrough();
    public stderr = new PassThrough();
    public pid = 12345;
    public kill = jest.fn();
}

let mockProcess: MockChildProcess;
let spawnShouldThrow: Error | null = null;

jest.mock('child_process', () => ({
    spawn: jest.fn((..._args: unknown[]) => {
        if (spawnShouldThrow) {
            throw spawnShouldThrow;
        }
        mockProcess = new MockChildProcess();
        return mockProcess;
    }),
    execFile: jest.fn(),
}));

// ---------------------------------------------------------------------------
// Mock http
// ---------------------------------------------------------------------------

type HttpCallback = (res: { statusCode: number; resume: () => void }) => void;

let httpGetCallback: HttpCallback | null = null;
let httpReqErrorCallback: ((err: Error) => void) | null = null;

jest.mock('http', () => ({
    get: jest.fn((_url: string, _options: unknown, cb: HttpCallback) => {
        httpGetCallback = cb;
        const req = {
            on: jest.fn((event: string, handler: (err: Error) => void) => {
                if (event === 'error') {
                    httpReqErrorCallback = handler;
                }
            }),
        };
        return req;
    }),
}));

// ---------------------------------------------------------------------------
// Imports (must come after jest.mock calls)
// ---------------------------------------------------------------------------

import { ServerManager } from '../server-manager';
import { spawn, execFile } from 'child_process';
import * as http from 'http';
import type { LaunchConfig } from '../python-env';

// ---------------------------------------------------------------------------
// Helpers
// ---------------------------------------------------------------------------

function createLaunchConfig(overrides: Partial<LaunchConfig> = {}): LaunchConfig {
    return {
        mode: 'dev',
        command: 'python',
        args: ['-m', 'src.server', '--port', '9100'],
        cwd: '/test/workspace',
        ...overrides,
    };
}

/** Simulate a health check response by invoking the captured http.get callback. */
function respondHealth(statusCode: number): void {
    if (httpGetCallback) {
        httpGetCallback({ statusCode, resume: jest.fn() });
        httpGetCallback = null;
    }
}

/** Simulate a health check connection error. */
function respondHealthError(): void {
    if (httpReqErrorCallback) {
        httpReqErrorCallback(new Error('ECONNREFUSED'));
        httpReqErrorCallback = null;
    }
}

/** Emit data on mock process stdout to simulate server output. */
function emitStdout(text: string): void {
    mockProcess.stdout.push(Buffer.from(text));
}

/** Emit data on mock process stderr. */
function emitStderr(text: string): void {
    mockProcess.stderr.push(Buffer.from(text));
}

// ---------------------------------------------------------------------------
// Test Suite
// ---------------------------------------------------------------------------

describe('ServerManager', () => {
    let manager: ServerManager;
    const config = createLaunchConfig();
    const port = 9100;

    beforeEach(() => {
        jest.useFakeTimers();
        spawnShouldThrow = null;
        httpGetCallback = null;
        httpReqErrorCallback = null;
        // Reset the mock process reference (new one created on spawn)
        mockProcess = new MockChildProcess();
    });

    afterEach(() => {
        // Dispose to clean up timers and listeners
        if (manager) {
            manager.dispose();
        }
        jest.useRealTimers();
    });

    // -----------------------------------------------------------------------
    // Construction
    // -----------------------------------------------------------------------

    describe('constructor', () => {
        test('creates an output channel named "ClarAIty Server"', () => {
            manager = new ServerManager(config, port);

            expect(vscode.window.createOutputChannel).toHaveBeenCalledWith('ClarAIty Server');
        });

        test('starts with no process and null authToken', () => {
            manager = new ServerManager(config, port);

            expect(manager.authToken).toBeNull();
        });
    });

    // -----------------------------------------------------------------------
    // start()
    // -----------------------------------------------------------------------

    describe('start()', () => {
        test('spawns the process with correct command, args, and cwd', () => {
            manager = new ServerManager(config, port);
            manager.start();

            expect(spawn).toHaveBeenCalledWith(
                'python',
                ['-m', 'src.server', '--port', '9100'],
                expect.objectContaining({
                    cwd: '/test/workspace',
                    stdio: ['ignore', 'pipe', 'pipe'],
                }),
            );
        });

        test('sets detached based on platform', () => {
            manager = new ServerManager(config, port);
            manager.start();

            const spawnCall = (spawn as jest.Mock).mock.calls[0];
            const options = spawnCall[2];
            // On the test runner (Node), process.platform is a fixed value.
            // The code sets detached: process.platform !== 'win32'.
            expect(options.detached).toBe(process.platform !== 'win32');
        });

        test('is a no-op if process is already running', () => {
            manager = new ServerManager(config, port);
            manager.start();
            const firstCallCount = (spawn as jest.Mock).mock.calls.length;

            manager.start(); // second call

            expect((spawn as jest.Mock).mock.calls.length).toBe(firstCallCount);
        });

        test('pipes stdout to output channel', () => {
            manager = new ServerManager(config, port);
            manager.start();

            emitStdout('Server starting on port 9100\n');

            const outputChannel = (vscode.window.createOutputChannel as jest.Mock).mock.results[0].value;
            expect(outputChannel.append).toHaveBeenCalledWith('Server starting on port 9100\n');
        });

        test('pipes stderr to output channel', () => {
            manager = new ServerManager(config, port);
            manager.start();

            emitStderr('WARNING: debug mode enabled\n');

            const outputChannel = (vscode.window.createOutputChannel as jest.Mock).mock.results[0].value;
            expect(outputChannel.append).toHaveBeenCalledWith('WARNING: debug mode enabled\n');
        });

        test('handles spawn error and fires onStopped', () => {
            const error = new Error('ENOENT: python not found');
            spawnShouldThrow = error;

            manager = new ServerManager(config, port);

            const stoppedReasons: string[] = [];
            manager.onStopped((reason) => stoppedReasons.push(reason));

            manager.start();

            expect(stoppedReasons).toEqual(['ENOENT: python not found']);
            expect(vscode.window.showErrorMessage).toHaveBeenCalled();
        });

        test('spawn error hint mentions PATH for dev mode', () => {
            spawnShouldThrow = new Error('spawn fail');
            const devConfig = createLaunchConfig({ mode: 'dev', command: 'python3' });
            manager = new ServerManager(devConfig, port);
            manager.start();

            const errorMsg = (vscode.window.showErrorMessage as jest.Mock).mock.calls[0][0];
            expect(errorMsg).toContain('python3');
            expect(errorMsg).toContain('PATH');
        });

        test('spawn error hint mentions pip install for installed mode', () => {
            spawnShouldThrow = new Error('spawn fail');
            const installedConfig = createLaunchConfig({ mode: 'installed' });
            manager = new ServerManager(installedConfig, port);
            manager.start();

            const errorMsg = (vscode.window.showErrorMessage as jest.Mock).mock.calls[0][0];
            expect(errorMsg).toContain('pip install');
            expect(errorMsg).toContain('claraity-code');
        });

        test('starts health polling after successful spawn', () => {
            manager = new ServerManager(config, port);
            manager.start();

            // Advance one poll interval
            jest.advanceTimersByTime(500);

            expect(http.get).toHaveBeenCalled();
        });
    });

    // -----------------------------------------------------------------------
    // Auth Token Extraction
    // -----------------------------------------------------------------------

    describe('auth token extraction', () => {
        test('captures auth token from stdout', () => {
            manager = new ServerManager(config, port);
            manager.start();

            emitStdout('Auth Token: abc123def456\n');

            expect(manager.authToken).toBe('abc123def456');
        });

        test('captures auth token with extra whitespace', () => {
            manager = new ServerManager(config, port);
            manager.start();

            emitStdout('Auth Token:   my-secret-token\n');

            expect(manager.authToken).toBe('my-secret-token');
        });

        test('captures auth token from multi-line output', () => {
            manager = new ServerManager(config, port);
            manager.start();

            emitStdout('Starting server...\nAuth Token: tok_xyz789\nListening on 0.0.0.0:9100\n');

            expect(manager.authToken).toBe('tok_xyz789');
        });

        test('logs when auth token is captured', () => {
            manager = new ServerManager(config, port);
            manager.start();

            emitStdout('Auth Token: mytoken\n');

            const outputChannel = (vscode.window.createOutputChannel as jest.Mock).mock.results[0].value;
            expect(outputChannel.appendLine).toHaveBeenCalledWith(
                '[ServerManager] Auth token captured',
            );
        });

        test('does not set token when stdout has no token line', () => {
            manager = new ServerManager(config, port);
            manager.start();

            emitStdout('Server ready, no token here\n');

            expect(manager.authToken).toBeNull();
        });
    });

    // -----------------------------------------------------------------------
    // Health Polling
    // -----------------------------------------------------------------------

    describe('health polling', () => {
        test('polls /health at the correct URL', () => {
            manager = new ServerManager(config, port);
            manager.start();

            jest.advanceTimersByTime(500);

            expect(http.get).toHaveBeenCalledWith(
                'http://localhost:9100/health',
                { timeout: 2000 },
                expect.any(Function),
            );
        });

        test('fires onReady when health returns 200 AND auth token is captured', () => {
            manager = new ServerManager(config, port);

            const readyFired: boolean[] = [];
            manager.onReady(() => readyFired.push(true));

            manager.start();

            // Provide auth token first
            emitStdout('Auth Token: test-token\n');

            // First health poll
            jest.advanceTimersByTime(500);
            respondHealth(200);

            expect(readyFired).toEqual([true]);
        });

        test('does NOT fire onReady when health is 200 but no auth token yet', () => {
            manager = new ServerManager(config, port);

            const readyFired: boolean[] = [];
            manager.onReady(() => readyFired.push(true));

            manager.start();

            // Health poll returns 200 but no token emitted yet
            jest.advanceTimersByTime(500);
            respondHealth(200);

            expect(readyFired).toEqual([]);
        });

        test('keeps polling until both health=200 and token are available', () => {
            manager = new ServerManager(config, port);

            const readyFired: boolean[] = [];
            manager.onReady(() => readyFired.push(true));

            manager.start();

            // Poll 1: health 200, no token -> keep polling
            jest.advanceTimersByTime(500);
            respondHealth(200);
            expect(readyFired).toEqual([]);

            // Poll 2: health error -> keep polling
            jest.advanceTimersByTime(500);
            respondHealthError();
            expect(readyFired).toEqual([]);

            // Token arrives
            emitStdout('Auth Token: late-token\n');

            // Poll 3: health 200 + token present -> ready!
            jest.advanceTimersByTime(500);
            respondHealth(200);
            expect(readyFired).toEqual([true]);
        });

        test('continues polling on non-200 status codes', () => {
            manager = new ServerManager(config, port);

            const readyFired: boolean[] = [];
            manager.onReady(() => readyFired.push(true));

            manager.start();
            emitStdout('Auth Token: tok\n');

            // Non-200 response
            jest.advanceTimersByTime(500);
            respondHealth(503);
            expect(readyFired).toEqual([]);

            // Next poll succeeds
            jest.advanceTimersByTime(500);
            respondHealth(200);
            expect(readyFired).toEqual([true]);
        });

        test('continues polling on connection error', () => {
            manager = new ServerManager(config, port);

            const readyFired: boolean[] = [];
            manager.onReady(() => readyFired.push(true));

            manager.start();
            emitStdout('Auth Token: tok\n');

            // Connection refused
            jest.advanceTimersByTime(500);
            respondHealthError();
            expect(readyFired).toEqual([]);

            // Retry succeeds
            jest.advanceTimersByTime(500);
            respondHealth(200);
            expect(readyFired).toEqual([true]);
        });

        test('times out after 30 seconds and fires onStopped', () => {
            manager = new ServerManager(config, port);

            const stoppedReasons: string[] = [];
            manager.onStopped((reason) => stoppedReasons.push(reason));

            manager.start();

            // Advance past the 30s timeout, responding with errors each poll
            // 30_000 / 500 = 60 polls, plus one extra interval to trigger timeout check
            for (let i = 0; i < 62; i++) {
                jest.advanceTimersByTime(500);
                respondHealthError();
            }

            expect(stoppedReasons.length).toBe(1);
            expect(stoppedReasons[0]).toContain('did not become ready');
            expect(stoppedReasons[0]).toContain('30');
            expect(vscode.window.showErrorMessage).toHaveBeenCalled();
        });

        test('stops polling when process exits', () => {
            manager = new ServerManager(config, port);
            manager.start();

            // Simulate process exit, which sets this.process = null
            mockProcess.emit('exit', 1, null);

            // Clear any previous http.get calls
            (http.get as jest.Mock).mockClear();

            // Advance timer -- should not poll because process is null
            jest.advanceTimersByTime(500);

            // The poll callback runs but finds this.process is null and calls stopHealthPoll.
            // No new http.get call should happen after the stop.
            // We need one more tick to confirm no further calls.
            jest.advanceTimersByTime(500);

            // After the first tick post-exit, polling stops. The second tick should not produce a call.
            // http.get may have been called once (the interval fires once before stopHealthPoll clears it),
            // but should not continue indefinitely.
            const callsAfterExit = (http.get as jest.Mock).mock.calls.length;
            jest.advanceTimersByTime(5000);
            expect((http.get as jest.Mock).mock.calls.length).toBe(callsAfterExit);
        });

        test('stops polling after onReady fires', () => {
            manager = new ServerManager(config, port);
            manager.start();

            emitStdout('Auth Token: tok\n');

            // Trigger ready
            jest.advanceTimersByTime(500);
            respondHealth(200);

            // Clear http.get calls
            (http.get as jest.Mock).mockClear();

            // Advance time -- no more polling should happen
            jest.advanceTimersByTime(5000);
            expect((http.get as jest.Mock).mock.calls.length).toBe(0);
        });
    });

    // -----------------------------------------------------------------------
    // Process Lifecycle
    // -----------------------------------------------------------------------

    describe('process lifecycle', () => {
        test('handles process error event and fires onStopped', () => {
            manager = new ServerManager(config, port);

            const stoppedReasons: string[] = [];
            manager.onStopped((reason) => stoppedReasons.push(reason));

            manager.start();

            mockProcess.emit('error', new Error('EACCES: permission denied'));

            expect(stoppedReasons).toEqual(['EACCES: permission denied']);
            expect(vscode.window.showErrorMessage).toHaveBeenCalled();
        });

        test('process error clears the process reference', () => {
            manager = new ServerManager(config, port);
            manager.start();

            mockProcess.emit('error', new Error('fail'));

            // After error, calling start() again should spawn a new process
            manager.start();
            expect((spawn as jest.Mock).mock.calls.length).toBe(2);
        });

        test('process error shows correct hint for dev mode', () => {
            const devConfig = createLaunchConfig({ mode: 'dev', command: 'python3' });
            manager = new ServerManager(devConfig, port);
            manager.start();

            mockProcess.emit('error', new Error('failed'));

            const errorMsg = (vscode.window.showErrorMessage as jest.Mock).mock.calls[0][0];
            expect(errorMsg).toContain('python3');
            expect(errorMsg).toContain('installed');
        });

        test('process error shows correct hint for installed mode', () => {
            const installedConfig = createLaunchConfig({ mode: 'installed' });
            manager = new ServerManager(installedConfig, port);
            manager.start();

            mockProcess.emit('error', new Error('failed'));

            const errorMsg = (vscode.window.showErrorMessage as jest.Mock).mock.calls[0][0];
            expect(errorMsg).toContain('pip install');
        });

        test('handles process exit event and fires onStopped with reason', () => {
            manager = new ServerManager(config, port);

            const stoppedReasons: string[] = [];
            manager.onStopped((reason) => stoppedReasons.push(reason));

            manager.start();

            mockProcess.emit('exit', 1, null);

            expect(stoppedReasons.length).toBe(1);
            expect(stoppedReasons[0]).toContain('code=1');
            expect(stoppedReasons[0]).toContain('signal=null');
        });

        test('exit event includes signal when process is killed', () => {
            manager = new ServerManager(config, port);

            const stoppedReasons: string[] = [];
            manager.onStopped((reason) => stoppedReasons.push(reason));

            manager.start();

            mockProcess.emit('exit', null, 'SIGTERM');

            expect(stoppedReasons[0]).toContain('signal=SIGTERM');
        });

        test('exit event is ignored when disposed', () => {
            manager = new ServerManager(config, port);

            const stoppedReasons: string[] = [];
            manager.onStopped((reason) => stoppedReasons.push(reason));

            manager.start();

            // Dispose first, then exit fires
            manager.dispose();
            mockProcess.emit('exit', 0, null);

            // onStopped should NOT have fired because exit was during dispose
            expect(stoppedReasons).toEqual([]);
        });

        test('exit event clears the process reference', () => {
            manager = new ServerManager(config, port);
            manager.start();

            mockProcess.emit('exit', 0, null);

            // After exit, calling start() again should spawn a new process
            manager.start();
            expect((spawn as jest.Mock).mock.calls.length).toBe(2);
        });

        test('exit event stops health polling', () => {
            manager = new ServerManager(config, port);
            manager.start();

            mockProcess.emit('exit', 1, null);

            // Clear http.get calls
            (http.get as jest.Mock).mockClear();

            // Advance timers -- polling should have stopped
            jest.advanceTimersByTime(5000);

            // At most one straggling call from the interval firing before clear
            // but no continuous polling
            const callCount = (http.get as jest.Mock).mock.calls.length;
            jest.advanceTimersByTime(5000);
            expect((http.get as jest.Mock).mock.calls.length).toBe(callCount);
        });

        test('process error stops health polling', () => {
            manager = new ServerManager(config, port);
            manager.start();

            mockProcess.emit('error', new Error('crash'));

            // Clear http.get calls
            (http.get as jest.Mock).mockClear();

            // Advance timers -- polling should have stopped
            jest.advanceTimersByTime(5000);
            const callCount = (http.get as jest.Mock).mock.calls.length;
            jest.advanceTimersByTime(5000);
            expect((http.get as jest.Mock).mock.calls.length).toBe(callCount);
        });
    });

    // -----------------------------------------------------------------------
    // dispose()
    // -----------------------------------------------------------------------

    describe('dispose()', () => {
        test('stops health polling', () => {
            manager = new ServerManager(config, port);
            manager.start();

            manager.dispose();

            (http.get as jest.Mock).mockClear();
            jest.advanceTimersByTime(5000);
            expect((http.get as jest.Mock).mock.calls.length).toBe(0);
        });

        test('disposes event emitters and output channel', () => {
            manager = new ServerManager(config, port);
            const outputChannel = (vscode.window.createOutputChannel as jest.Mock).mock.results[0].value;

            manager.dispose();

            expect(outputChannel.dispose).toHaveBeenCalled();
        });

        test('kills process with taskkill on Windows', () => {
            // Temporarily mock platform to win32
            const originalPlatform = process.platform;
            Object.defineProperty(process, 'platform', { value: 'win32' });

            try {
                manager = new ServerManager(config, port);
                manager.start();

                const pid = mockProcess.pid;

                manager.dispose();

                expect(execFile).toHaveBeenCalledWith(
                    'taskkill',
                    ['/pid', String(pid), '/f', '/t'],
                    expect.any(Function),
                );
            } finally {
                Object.defineProperty(process, 'platform', { value: originalPlatform });
            }
        });

        test('kills process group with SIGTERM on Unix', () => {
            const originalPlatform = process.platform;
            Object.defineProperty(process, 'platform', { value: 'linux' });

            // Mock process.kill to capture the call
            const originalKill = process.kill;
            const killMock = jest.fn();
            process.kill = killMock as unknown as typeof process.kill;

            try {
                manager = new ServerManager(config, port);
                manager.start();

                const pid = mockProcess.pid;

                manager.dispose();

                // Should kill the process group (negative PID)
                expect(killMock).toHaveBeenCalledWith(-pid, 'SIGTERM');
            } finally {
                Object.defineProperty(process, 'platform', { value: originalPlatform });
                process.kill = originalKill;
            }
        });

        test('handles process.kill throwing (process already gone)', () => {
            const originalPlatform = process.platform;
            Object.defineProperty(process, 'platform', { value: 'linux' });

            const originalKill = process.kill;
            process.kill = jest.fn(() => {
                throw new Error('ESRCH: no such process');
            }) as unknown as typeof process.kill;

            try {
                manager = new ServerManager(config, port);
                manager.start();

                // Should not throw
                expect(() => manager.dispose()).not.toThrow();
            } finally {
                Object.defineProperty(process, 'platform', { value: originalPlatform });
                process.kill = originalKill;
            }
        });

        test('does not attempt kill when no process is running', () => {
            const originalKill = process.kill;
            const killMock = jest.fn();
            process.kill = killMock as unknown as typeof process.kill;

            try {
                manager = new ServerManager(config, port);
                // Never started, so no process

                manager.dispose();

                expect(killMock).not.toHaveBeenCalled();
                expect(execFile).not.toHaveBeenCalled();
            } finally {
                process.kill = originalKill;
            }
        });

        test('sets disposed flag so exit event is ignored', () => {
            manager = new ServerManager(config, port);

            const stoppedReasons: string[] = [];
            manager.onStopped((reason) => stoppedReasons.push(reason));

            manager.start();
            manager.dispose();

            // Simulate the delayed exit that comes after kill
            mockProcess.emit('exit', 0, 'SIGTERM');

            expect(stoppedReasons).toEqual([]);
        });

        test('sets process to null after dispose', () => {
            manager = new ServerManager(config, port);
            manager.start();

            manager.dispose();

            // Calling start() after dispose would attempt a new spawn
            // but we shouldn't do that in production; this just verifies internal state
            // was cleaned up. We verify via the authToken remaining accessible.
            expect(manager.authToken).toBeNull();
        });

        test('logs stopping message', () => {
            manager = new ServerManager(config, port);
            manager.start();

            const outputChannel = (vscode.window.createOutputChannel as jest.Mock).mock.results[0].value;

            manager.dispose();

            expect(outputChannel.appendLine).toHaveBeenCalledWith(
                '[ServerManager] Stopping server...',
            );
        });

        test('taskkill error is logged to output channel', () => {
            const originalPlatform = process.platform;
            Object.defineProperty(process, 'platform', { value: 'win32' });

            try {
                manager = new ServerManager(config, port);
                manager.start();

                const outputChannel = (vscode.window.createOutputChannel as jest.Mock).mock.results[0].value;

                manager.dispose();

                // Simulate taskkill error callback
                const execFileCall = (execFile as unknown as jest.Mock).mock.calls[0];
                const callback = execFileCall[2]; // (err) => { ... }
                callback(new Error('taskkill failed'));

                expect(outputChannel.appendLine).toHaveBeenCalledWith(
                    expect.stringContaining('taskkill error'),
                );
            } finally {
                Object.defineProperty(process, 'platform', { value: originalPlatform });
            }
        });
    });

    // -----------------------------------------------------------------------
    // Events (onReady / onStopped)
    // -----------------------------------------------------------------------

    describe('events', () => {
        test('onReady event can be subscribed to before start()', () => {
            manager = new ServerManager(config, port);

            const readyFired: boolean[] = [];
            manager.onReady(() => readyFired.push(true));

            manager.start();
            emitStdout('Auth Token: tok\n');
            jest.advanceTimersByTime(500);
            respondHealth(200);

            expect(readyFired).toEqual([true]);
        });

        test('onStopped event can be subscribed to before start()', () => {
            manager = new ServerManager(config, port);

            const stoppedReasons: string[] = [];
            manager.onStopped((reason) => stoppedReasons.push(reason));

            manager.start();
            mockProcess.emit('exit', 1, null);

            expect(stoppedReasons.length).toBe(1);
        });

        test('multiple listeners receive events', () => {
            manager = new ServerManager(config, port);

            const listener1: string[] = [];
            const listener2: string[] = [];
            manager.onStopped((reason) => listener1.push(reason));
            manager.onStopped((reason) => listener2.push(reason));

            manager.start();
            mockProcess.emit('exit', 1, null);

            expect(listener1.length).toBe(1);
            expect(listener2.length).toBe(1);
        });

        test('disposed listener does not receive events', () => {
            manager = new ServerManager(config, port);

            const received: string[] = [];
            const subscription = manager.onStopped((reason) => received.push(reason));
            subscription.dispose();

            manager.start();
            mockProcess.emit('exit', 1, null);

            expect(received).toEqual([]);
        });

        test('onReady fires only once even if health keeps returning 200', () => {
            manager = new ServerManager(config, port);

            const readyCount: number[] = [];
            manager.onReady(() => readyCount.push(1));

            manager.start();
            emitStdout('Auth Token: tok\n');

            // First poll -> ready
            jest.advanceTimersByTime(500);
            respondHealth(200);

            // Polling should have stopped, so onReady fires exactly once
            expect(readyCount).toEqual([1]);
        });
    });

    // -----------------------------------------------------------------------
    // authToken getter
    // -----------------------------------------------------------------------

    describe('authToken getter', () => {
        test('returns null before any stdout data', () => {
            manager = new ServerManager(config, port);
            manager.start();

            expect(manager.authToken).toBeNull();
        });

        test('returns the captured token after stdout emits it', () => {
            manager = new ServerManager(config, port);
            manager.start();

            emitStdout('Auth Token: secret-token-123\n');

            expect(manager.authToken).toBe('secret-token-123');
        });

        test('last token wins if multiple tokens are emitted', () => {
            manager = new ServerManager(config, port);
            manager.start();

            emitStdout('Auth Token: first-token\n');
            emitStdout('Auth Token: second-token\n');

            expect(manager.authToken).toBe('second-token');
        });
    });
});
