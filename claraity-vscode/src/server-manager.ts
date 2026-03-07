/**
 * ServerManager - Spawns and manages the ClarAIty Python server process.
 *
 * Responsibilities:
 * - Spawn the server using a LaunchConfig (dev or installed mode)
 * - Poll GET /health until the server is ready (or timeout)
 * - Pipe stdout/stderr to a VS Code Output Channel
 * - Kill the process on dispose()
 */

import * as vscode from 'vscode';
import { spawn, ChildProcess, execFile } from 'child_process';
import * as http from 'http';
import { LaunchConfig, PYPI_PACKAGE } from './python-env';

const HEALTH_POLL_INTERVAL_MS = 500;
const HEALTH_POLL_TIMEOUT_MS = 30_000;

export class ServerManager implements vscode.Disposable {
    private process: ChildProcess | null = null;
    private healthTimer: ReturnType<typeof setInterval> | null = null;
    private outputChannel: vscode.OutputChannel;
    private disposed = false;
    private _authToken: string | null = null;

    private _onReady = new vscode.EventEmitter<void>();
    public readonly onReady = this._onReady.event;

    private _onStopped = new vscode.EventEmitter<string>();
    public readonly onStopped = this._onStopped.event;

    /** Auth token captured from server stdout. Available after onReady fires. */
    get authToken(): string | null {
        return this._authToken;
    }

    constructor(
        private readonly launchConfig: LaunchConfig,
        private readonly port: number,
    ) {
        this.outputChannel = vscode.window.createOutputChannel('ClarAIty Server');
    }

    /**
     * Spawn the Python server and wait for it to become healthy.
     */
    start(): void {
        if (this.process) {
            return;
        }

        const { command, args, cwd } = this.launchConfig;

        this.outputChannel.appendLine(
            `[ServerManager] Starting (${this.launchConfig.mode} mode): ${command} ${args.join(' ')}`,
        );
        this.outputChannel.appendLine(`[ServerManager] Working directory: ${cwd}`);

        try {
            this.process = spawn(command, args, {
                cwd,
                stdio: ['ignore', 'pipe', 'pipe'],
                // On Windows, spawn in a new process group so taskkill /t
                // can kill the entire tree. On Unix this is harmless.
                detached: process.platform !== 'win32',
            });
        } catch (err: unknown) {
            const msg = err instanceof Error ? err.message : String(err);
            this.outputChannel.appendLine(`[ServerManager] Failed to spawn process: ${msg}`);
            const hint = this.launchConfig.mode === 'dev'
                ? `Is "${command}" on your PATH?`
                : `Try: pip install ${PYPI_PACKAGE}`;
            vscode.window.showErrorMessage(
                `ClarAIty: Failed to start Python server. ${hint}\n${msg}`,
            );
            this._onStopped.fire(msg);
            return;
        }

        // Pipe stdout/stderr to the output channel and capture auth token
        this.process.stdout?.on('data', (data: Buffer) => {
            const text = data.toString();
            this.outputChannel.append(text);

            // Parse auth token from server output (printed as "Auth Token: <token>")
            const tokenMatch = text.match(/Auth Token:\s*(\S+)/);
            if (tokenMatch) {
                this._authToken = tokenMatch[1];
                this.outputChannel.appendLine('[ServerManager] Auth token captured');
            }
        });
        this.process.stderr?.on('data', (data: Buffer) => {
            this.outputChannel.append(data.toString());
        });

        // Handle unexpected exit
        this.process.on('error', (err) => {
            this.outputChannel.appendLine(`[ServerManager] Process error: ${err.message}`);
            this.stopHealthPoll();
            const hint = this.launchConfig.mode === 'dev'
                ? `Is "${command}" installed?`
                : `Try: pip install ${PYPI_PACKAGE}`;
            vscode.window.showErrorMessage(
                `ClarAIty: Python server failed to start. ${hint}\n${err.message}`,
            );
            this._onStopped.fire(err.message);
            this.process = null;
        });

        this.process.on('exit', (code, signal) => {
            if (this.disposed) {
                return; // Expected exit during dispose
            }
            const reason = `Process exited (code=${code}, signal=${signal})`;
            this.outputChannel.appendLine(`[ServerManager] ${reason}`);
            this.stopHealthPoll();
            this._onStopped.fire(reason);
            this.process = null;
        });

        // Start polling /health
        this.startHealthPoll();
    }

    /**
     * Poll the /health endpoint until the server responds with 200.
     */
    private startHealthPoll(): void {
        const startTime = Date.now();

        this.healthTimer = setInterval(() => {
            // Timeout check
            if (Date.now() - startTime > HEALTH_POLL_TIMEOUT_MS) {
                this.stopHealthPoll();
                const msg = `Server did not become ready within ${HEALTH_POLL_TIMEOUT_MS / 1000}s`;
                this.outputChannel.appendLine(`[ServerManager] ${msg}`);
                vscode.window.showErrorMessage(`ClarAIty: ${msg}`);
                this._onStopped.fire(msg);
                return;
            }

            // If the process already exited, stop polling
            if (!this.process) {
                this.stopHealthPoll();
                return;
            }

            const req = http.get(
                `http://localhost:${this.port}/health`,
                { timeout: 2000 },
                (res) => {
                    if (res.statusCode === 200) {
                        if (this._authToken) {
                            // Both healthy and token captured -- ready
                            this.stopHealthPoll();
                            this.outputChannel.appendLine(
                                '[ServerManager] Server is ready (health check passed, token captured)',
                            );
                            this._onReady.fire();
                        }
                        // else: healthy but token not yet captured from stdout -- keep polling
                    }
                    // Consume response data to free memory
                    res.resume();
                },
            );

            req.on('error', () => {
                // Server not ready yet -- ignore and retry on next tick
            });
        }, HEALTH_POLL_INTERVAL_MS);
    }

    private stopHealthPoll(): void {
        if (this.healthTimer) {
            clearInterval(this.healthTimer);
            this.healthTimer = null;
        }
    }

    dispose(): void {
        this.disposed = true;
        this.stopHealthPoll();

        if (this.process && this.process.pid) {
            this.outputChannel.appendLine('[ServerManager] Stopping server...');

            if (process.platform === 'win32') {
                // Windows: use taskkill to kill the process tree.
                // Python on Windows doesn't respond well to signals.
                execFile(
                    'taskkill',
                    ['/pid', String(this.process.pid), '/f', '/t'],
                    (err) => {
                        if (err) {
                            this.outputChannel.appendLine(
                                `[ServerManager] taskkill error: ${err.message}`,
                            );
                        }
                    },
                );
            } else {
                // Unix: kill the process group (negative PID)
                try {
                    process.kill(-this.process.pid, 'SIGTERM');
                } catch {
                    // Process may already be gone
                }
            }

            this.process = null;
        }

        this._onReady.dispose();
        this._onStopped.dispose();
        this.outputChannel.dispose();
    }
}
