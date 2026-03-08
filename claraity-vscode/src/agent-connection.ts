/**
 * WebSocket client for connecting to the ClarAIty Python server.
 *
 * Manages connection lifecycle, reconnection with exponential backoff,
 * and message routing.
 */

import * as vscode from 'vscode';
import { ServerMessage, ClientMessage } from './types';

// Node.js built-in WebSocket (available in Node 20+)
import WebSocket from 'ws';

export class AgentConnection {
    private ws: WebSocket | null = null;
    private reconnectTimer: ReturnType<typeof setTimeout> | null = null;
    private reconnectDelay = 1000;
    private shouldReconnect = true;
    private authToken: string | null = null;
    private awaitingAuth = false;

    // Events for consumers
    private _onMessage = new vscode.EventEmitter<ServerMessage>();
    public readonly onMessage = this._onMessage.event;

    private _onConnected = new vscode.EventEmitter<void>();
    public readonly onConnected = this._onConnected.event;

    private _onDisconnected = new vscode.EventEmitter<void>();
    public readonly onDisconnected = this._onDisconnected.event;

    constructor(private url: string = 'ws://localhost:9120/ws') {}

    /** Store the auth token for use on connect/reconnect. */
    setAuthToken(token: string): void {
        this.authToken = token;
    }

    connect(): void {
        if (this.ws && (this.ws.readyState === WebSocket.OPEN
                     || this.ws.readyState === WebSocket.CONNECTING)) {
            return;
        }

        this.shouldReconnect = true;

        try {
            this.ws = new WebSocket(this.url);

            this.ws.on('open', () => {
                console.log('[ClarAIty] WebSocket open, sending auth handshake...');
                this.reconnectDelay = 1000; // Reset backoff
                // Send auth as first message instead of URL param
                if (this.authToken) {
                    this.ws?.send(JSON.stringify({
                        type: 'auth',
                        token: this.authToken,
                    }));
                    this.awaitingAuth = true;
                } else {
                    // No token available -- fire connected and hope for the best
                    console.warn('[ClarAIty] No auth token set, connection may be rejected');
                    this._onConnected.fire();
                }
            });

            this.ws.on('message', (data: WebSocket.Data) => {
                try {
                    const msg = JSON.parse(data.toString()) as ServerMessage;

                    // Handle auth handshake response
                    if (this.awaitingAuth) {
                        this.awaitingAuth = false;
                        if (msg.type === 'error' && (msg as any).error_type === 'auth_failed') {
                            console.error('[ClarAIty] Authentication failed');
                            this.shouldReconnect = false;
                            this.ws?.close();
                            return;
                        }
                        // session_info = auth succeeded
                        this._onConnected.fire();
                        this._onMessage.fire(msg);
                        return;
                    }

                    this._onMessage.fire(msg);
                } catch (e) {
                    console.error('[ClarAIty] Failed to parse message:', e);
                }
            });

            this.ws.on('close', () => {
                console.log('[ClarAIty] Disconnected from server');
                this.awaitingAuth = false;
                this._onDisconnected.fire();
                if (this.shouldReconnect) {
                    this.scheduleReconnect();
                }
            });

            this.ws.on('error', (err: Error) => {
                console.error('[ClarAIty] WebSocket error:', err.message);
                // Close event will follow and trigger reconnect
            });

        } catch (e) {
            console.error('[ClarAIty] Failed to create WebSocket:', e);
            if (this.shouldReconnect) {
                this.scheduleReconnect();
            }
        }
    }

    disconnect(): void {
        this.shouldReconnect = false;
        if (this.reconnectTimer) {
            clearTimeout(this.reconnectTimer);
            this.reconnectTimer = null;
        }
        if (this.ws) {
            this.ws.close();
            this.ws = null;
        }
    }

    send(message: ClientMessage): void {
        if (this.ws && this.ws.readyState === WebSocket.OPEN) {
            this.ws.send(JSON.stringify(message));
        } else {
            console.warn('[ClarAIty] Cannot send: not connected');
        }
    }

    get isConnected(): boolean {
        return this.ws !== null && this.ws.readyState === WebSocket.OPEN;
    }

    updateUrl(url: string): void {
        this.url = url;
    }

    private scheduleReconnect(): void {
        if (this.reconnectTimer) {
            return;
        }
        console.log(`[ClarAIty] Reconnecting in ${this.reconnectDelay}ms...`);
        this.reconnectTimer = setTimeout(() => {
            this.reconnectTimer = null;
            this.reconnectDelay = Math.min(this.reconnectDelay * 2, 30000);
            this.connect();
        }, this.reconnectDelay);
    }

    dispose(): void {
        this.disconnect();
        this._onMessage.dispose();
        this._onConnected.dispose();
        this._onDisconnected.dispose();
    }
}
