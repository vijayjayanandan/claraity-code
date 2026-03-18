/**
 * stdio+TCP connection to the ClarAIty agent.
 *
 * Spawns the agent binary (or Python fallback) with --stdio and --data-port.
 * - stdin: sends commands TO agent (chat_message, interrupt, etc.)
 * - TCP socket: receives events FROM agent (text_delta, stream_end, etc.)
 *
 * Binary resolution order:
 * 1. Bundled binary: <extensionPath>/bin/claraity-server.exe (or claraity-server on Unix)
 * 2. Python fallback: python -m src.server (dev mode)
 *
 * Why TCP instead of stdout pipes?
 * On Windows, the VS Code Extension Host has a libuv issue where pipe data
 * events do not fire reliably. TCP sockets use a different libuv code path
 * and work correctly.
 */

import * as vscode from 'vscode';
import * as net from 'net';
import { spawn, ChildProcess, execFile } from 'child_process';
import * as fs from 'fs';
import * as path from 'path';
import { ServerMessage, ClientMessage } from './types';
import { wrapNotification, isJsonRpc, unwrapMessage } from './jsonrpc';

export interface LaunchConfig {
    command: string;
    args: string[];
    cwd: string;
}

/** Max auto-restart attempts before giving up. */
const MAX_RESTART_ATTEMPTS = 3;

/** Base delay (ms) between restart attempts (doubles each time). */
const RESTART_BASE_DELAY_MS = 2000;

/** Seconds to wait for stream_start after sending chat_message. */
const RESPONSE_TIMEOUT_S = 30;

export class StdioConnection implements vscode.Disposable {
    private process: ChildProcess | null = null;
    private tcpServer: net.Server | null = null;
    private dataSocket: net.Socket | null = null;
    private socketBuffer = '';
    private serverOutputChannel: vscode.OutputChannel;
    private _apiKey: string = '';
    private _tavilyKey: string = '';
    private _disposed = false;

    // Auto-restart state
    private _restartCount = 0;
    private _restartTimer: ReturnType<typeof setTimeout> | null = null;
    private _intentionalDisconnect = false;

    // Response timeout: detect hung agent after sending chat_message
    private _responseTimer: ReturnType<typeof setTimeout> | null = null;

    // Same events as AgentConnection
    private _onMessage = new vscode.EventEmitter<ServerMessage>();
    public readonly onMessage = this._onMessage.event;

    private _onConnected = new vscode.EventEmitter<void>();
    public readonly onConnected = this._onConnected.event;

    private _onDisconnected = new vscode.EventEmitter<void>();
    public readonly onDisconnected = this._onDisconnected.event;

    constructor(
        private readonly launchConfig: LaunchConfig,
        private readonly log?: vscode.OutputChannel,
        private readonly extensionPath?: string,
    ) {
        this.serverOutputChannel = vscode.window.createOutputChannel('ClarAIty Server');
    }

    /**
     * Set the API key to inject as CLARAITY_API_KEY env var when spawning.
     */
    setApiKey(key: string): void {
        this._apiKey = key;
    }

    /**
     * Set the Tavily key to inject as TAVILY_API_KEY env var when spawning.
     */
    setTavilyKey(key: string): void {
        this._tavilyKey = key;
    }

    /**
     * Resolve the agent binary path.
     * Returns bundled binary if it exists, otherwise falls back to Python.
     * Respects claraity.devMode setting: "always" forces Python source mode.
     */
    private resolveAgent(): { command: string; args: string[] } {
        const devMode = vscode.workspace.getConfiguration('claraity').get<string>('devMode', 'auto');

        if (devMode !== 'always' && this.extensionPath) {
            const binaryName = process.platform === 'win32'
                ? 'claraity-server.exe'
                : 'claraity-server';

            // Check both flat layout (bin/claraity-server.exe) and
            // PyInstaller one-folder layout (bin/claraity-server/claraity-server.exe)
            const candidates = [
                path.join(this.extensionPath, 'bin', binaryName),
                path.join(this.extensionPath, 'bin', binaryName.replace(/\.exe$/, ''), binaryName),
            ];

            for (const binPath of candidates) {
                if (fs.existsSync(binPath)) {
                    this.logLine(`[STDIO] Using bundled binary: ${binPath}`);
                    return {
                        command: binPath,
                        args: ['--workdir', this.launchConfig.cwd],
                    };
                }
            }
        } else if (devMode === 'always') {
            this.logLine('[STDIO] devMode=always — skipping binary, using Python source');
        }

        // Fallback: Python mode (dev)
        this.logLine('[STDIO] Using Python fallback');
        return {
            command: this.launchConfig.command,
            args: ['-u', ...this.launchConfig.args],
        };
    }

    /**
     * Create a local TCP server, then spawn the agent with --data-port pointing to it.
     * Agent connects back to this port for sending JSON events.
     */
    connect(): void {
        if (this.process) {
            return;
        }

        const { cwd } = this.launchConfig;
        const resolved = this.resolveAgent();

        // Create TCP server on random port for receiving events from agent
        this.tcpServer = net.createServer((socket) => {
            this.dataSocket = socket;
            socket.setEncoding('utf-8');

            let firstMessage = true;

            socket.on('data', (chunk: string | Buffer) => {
                this.socketBuffer += chunk;

                // Process complete lines
                let newlineIdx: number;
                while ((newlineIdx = this.socketBuffer.indexOf('\n')) !== -1) {
                    const line = this.socketBuffer.substring(0, newlineIdx).trim();
                    this.socketBuffer = this.socketBuffer.substring(newlineIdx + 1);
                    if (!line) { continue; }

                    try {
                        let parsed = JSON.parse(line);
                        if (isJsonRpc(parsed)) {
                            parsed = unwrapMessage(parsed);
                        }
                        const msg = parsed as ServerMessage;

                        if (firstMessage) {
                            firstMessage = false;
                            this._restartCount = 0; // Reset on successful connection
                            this.logLine('[STDIO] Connected (received first message)');
                            this._onConnected.fire();
                        }

                        // Clear response timeout when we receive any message
                        // (stream_start, text_delta, etc.)
                        if (msg.type === 'stream_start' || msg.type === 'text_delta' || msg.type === 'error') {
                            this.clearResponseTimeout();
                        }

                        this._onMessage.fire(msg);
                    } catch (e) {
                        this.logLine(`[STDIO] Parse error: ${(e as Error).message}`);
                    }
                }
            });

            socket.on('error', (err) => {
                this.logLine(`[STDIO] TCP socket error: ${err.message}`);
            });

            socket.on('close', () => {
                this.dataSocket = null;
            });
        });

        this.tcpServer.listen(0, '127.0.0.1', () => {
            const addr = this.tcpServer!.address() as net.AddressInfo;
            const dataPort = addr.port;

            // Add --stdio and --data-port to resolved args
            const spawnArgs = [...resolved.args, '--stdio', '--data-port', String(dataPort)];

            this.logLine(`[STDIO] Spawning: ${resolved.command} ${spawnArgs.join(' ')}`);
            this.logLine(`[STDIO] CWD: ${cwd}`);

            try {
                const spawnEnv: Record<string, string> = {
                    ...process.env as Record<string, string>,
                    PYTHONUNBUFFERED: '1',
                };
                if (this._apiKey) {
                    spawnEnv.CLARAITY_API_KEY = this._apiKey;
                }
                if (this._tavilyKey) {
                    spawnEnv.TAVILY_API_KEY = this._tavilyKey;
                }

                this.process = spawn(resolved.command, spawnArgs, {
                    cwd,
                    stdio: ['pipe', 'ignore', 'pipe'],  // stdin + stderr only
                    env: spawnEnv,
                });
            } catch (e) {
                this.logLine(`[STDIO] Failed to spawn: ${e}`);
                this.tcpServer?.close();
                return;
            }

            // Pipe stderr to Output Channel
            if (this.process.stderr) {
                this.process.stderr.on('data', (data: Buffer) => {
                    this.serverOutputChannel.append(data.toString());
                });
            }

            this.process.on('exit', (code, signal) => {
                this.logLine(`[STDIO] Process exited (code=${code}, signal=${signal})`);
                this.clearResponseTimeout();
                this._onDisconnected.fire();
                this.cleanup();
                this.maybeAutoRestart(`exit code=${code}, signal=${signal}`);
            });

            this.process.on('error', (err: Error) => {
                this.logLine(`[STDIO] Process error: ${err.message}`);
                this.clearResponseTimeout();
                this._onDisconnected.fire();
                this.cleanup();
                this.maybeAutoRestart(err.message);
            });
        });

        this.tcpServer.on('error', (err) => {
            this.logLine(`[STDIO] TCP server error: ${err.message}`);
        });
    }

    /**
     * Send a ClientMessage by writing JSON + newline to stdin.
     * For chat_message, starts a response timeout to detect hung agents.
     */
    send(message: ClientMessage): void {
        if (this.process?.stdin && !this.process.stdin.destroyed) {
            const wrapped = wrapNotification(message as Record<string, any>);
            const line = JSON.stringify(wrapped) + '\n';
            this.process.stdin.write(line, (err) => {
                if (err) {
                    this.logLine(`[STDIO] stdin write error: ${err.message}`);
                    // Stdin pipe is broken — agent is dead
                    this._onMessage.fire({
                        type: 'error',
                        error_type: 'connection_error',
                        user_message: 'Lost connection to agent. Attempting to restart...',
                        recoverable: true,
                    } as ServerMessage);
                    this._onDisconnected.fire();
                    this.cleanup();
                    this.maybeAutoRestart('stdin write error');
                }
            });

            // Start response timeout for chat messages
            if (message.type === 'chat_message') {
                this.startResponseTimeout();
            }
        } else {
            this.logLine('[STDIO] Cannot send: process not running');
            // Notify the webview that the message couldn't be sent
            this._onMessage.fire({
                type: 'error',
                error_type: 'connection_error',
                user_message: 'Agent is not running. Attempting to restart...',
                recoverable: true,
            } as ServerMessage);
            this.maybeAutoRestart('process not running on send');
        }
    }

    get isConnected(): boolean {
        return this.process !== null && !this.process.killed;
    }

    /**
     * Intentionally disconnect — does NOT trigger auto-restart.
     */
    disconnect(): void {
        if (!this.process) {
            return;
        }

        this._intentionalDisconnect = true;
        this.clearResponseTimeout();
        this.logLine('[STDIO] Disconnecting...');

        if (this.process.stdin && !this.process.stdin.destroyed) {
            this.process.stdin.end();
        }

        const proc = this.process;
        const pid = proc.pid;
        setTimeout(() => {
            if (proc && !proc.killed && pid) {
                this.logLine(`[STDIO] Force killing process ${pid}`);
                if (process.platform === 'win32') {
                    execFile('taskkill', ['/pid', String(pid), '/f', '/t'], () => {});
                } else {
                    try { proc.kill('SIGTERM'); } catch { /* already dead */ }
                }
            }
        }, 3000);
    }

    /**
     * Force restart: kill current process and reconnect.
     * Resets restart counter so subsequent crashes get full retry budget.
     */
    restart(): void {
        this.logLine('[STDIO] Manual restart requested');
        this._restartCount = 0;
        this._intentionalDisconnect = true; // Don't double-restart
        this.clearResponseTimeout();

        if (this.process) {
            const proc = this.process;
            const pid = proc.pid;
            this.cleanup();
            // Force kill then reconnect
            if (pid) {
                if (process.platform === 'win32') {
                    execFile('taskkill', ['/pid', String(pid), '/f', '/t'], () => {});
                } else {
                    try { proc.kill('SIGKILL'); } catch { /* already dead */ }
                }
            }
        }

        this._intentionalDisconnect = false;
        setTimeout(() => this.connect(), 500);
    }

    // Stubs for AgentConnection interface compatibility
    setAuthToken(_token: string): void { /* no-op */ }
    updateUrl(_url: string): void { /* no-op */ }

    // ── Auto-restart logic ──

    /**
     * Called after process exit/error. Attempts restart with exponential backoff.
     */
    private maybeAutoRestart(reason: string): void {
        if (this._disposed || this._intentionalDisconnect) {
            return;
        }

        if (this._restartCount >= MAX_RESTART_ATTEMPTS) {
            this.logLine(`[STDIO] Auto-restart exhausted (${MAX_RESTART_ATTEMPTS} attempts). Reason: ${reason}`);
            vscode.window.showErrorMessage(
                `ClarAIty agent stopped unexpectedly (${reason}). Click "Restart" to try again.`,
                'Restart',
            ).then((choice) => {
                if (choice === 'Restart') {
                    this.restart();
                }
            });
            return;
        }

        this._restartCount++;
        const delay = RESTART_BASE_DELAY_MS * Math.pow(2, this._restartCount - 1);
        this.logLine(`[STDIO] Auto-restart attempt ${this._restartCount}/${MAX_RESTART_ATTEMPTS} in ${delay}ms (reason: ${reason})`);

        this._restartTimer = setTimeout(() => {
            this._restartTimer = null;
            if (!this._disposed) {
                this.connect();
            }
        }, delay);
    }

    // ── Response timeout logic ──

    /**
     * Start a timer: if no stream_start/text_delta/error arrives within
     * RESPONSE_TIMEOUT_S, fire a synthetic error so the webview knows.
     */
    private startResponseTimeout(): void {
        this.clearResponseTimeout();
        this._responseTimer = setTimeout(() => {
            this._responseTimer = null;
            this.logLine(`[STDIO] Response timeout (${RESPONSE_TIMEOUT_S}s) — agent may be hung`);
            this._onMessage.fire({
                type: 'error',
                error_type: 'response_timeout',
                user_message: `Agent did not respond within ${RESPONSE_TIMEOUT_S} seconds. It may have crashed or is unresponsive.`,
                recoverable: true,
            } as ServerMessage);
        }, RESPONSE_TIMEOUT_S * 1000);
    }

    private clearResponseTimeout(): void {
        if (this._responseTimer) {
            clearTimeout(this._responseTimer);
            this._responseTimer = null;
        }
    }

    // ── Cleanup ──

    private cleanup(): void {
        this.dataSocket?.destroy();
        this.dataSocket = null;
        this.tcpServer?.close();
        this.tcpServer = null;
        this.process = null;
    }

    private logLine(msg: string): void {
        this.log?.appendLine(msg);
    }

    dispose(): void {
        this._disposed = true;
        this._intentionalDisconnect = true;
        this.clearResponseTimeout();
        if (this._restartTimer) {
            clearTimeout(this._restartTimer);
            this._restartTimer = null;
        }
        this.disconnect();
        this.cleanup();
        this._onMessage.dispose();
        this._onConnected.dispose();
        this._onDisconnected.dispose();
        this.serverOutputChannel.dispose();
    }
}
