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

export class StdioConnection implements vscode.Disposable {
    private process: ChildProcess | null = null;
    private tcpServer: net.Server | null = null;
    private dataSocket: net.Socket | null = null;
    private socketBuffer = '';
    private serverOutputChannel: vscode.OutputChannel;
    private _apiKey: string = '';
    private _tavilyKey: string = '';

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
     */
    private resolveAgent(): { command: string; args: string[] } {
        if (this.extensionPath) {
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

            socket.on('data', (chunk: string) => {
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
                            this.logLine('[STDIO] Connected (received first message)');
                            this._onConnected.fire();
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
                this._onDisconnected.fire();
                this.cleanup();
            });

            this.process.on('error', (err: Error) => {
                this.logLine(`[STDIO] Process error: ${err.message}`);
                this._onDisconnected.fire();
                this.cleanup();
            });
        });

        this.tcpServer.on('error', (err) => {
            this.logLine(`[STDIO] TCP server error: ${err.message}`);
        });
    }

    /**
     * Send a ClientMessage by writing JSON + newline to stdin.
     */
    send(message: ClientMessage): void {
        if (this.process?.stdin && !this.process.stdin.destroyed) {
            const wrapped = wrapNotification(message as Record<string, any>);
            const line = JSON.stringify(wrapped) + '\n';
            this.process.stdin.write(line);
        } else {
            this.logLine('[STDIO] Cannot send: process not running');
        }
    }

    get isConnected(): boolean {
        return this.process !== null && !this.process.killed;
    }

    disconnect(): void {
        if (!this.process) {
            return;
        }

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

    // Stubs for AgentConnection interface compatibility
    setAuthToken(_token: string): void { /* no-op */ }
    updateUrl(_url: string): void { /* no-op */ }

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
        this.disconnect();
        this.cleanup();
        this._onMessage.dispose();
        this._onConnected.dispose();
        this._onDisconnected.dispose();
        this.serverOutputChannel.dispose();
    }
}
