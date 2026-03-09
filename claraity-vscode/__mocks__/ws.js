/**
 * Mock for the 'ws' WebSocket module.
 *
 * Provides a controllable WebSocket that tests can use to simulate
 * server connections, messages, and disconnections.
 */

const EventEmitter = require('events');

class MockWebSocket extends EventEmitter {
    constructor(url) {
        super();
        this.url = url;
        this.readyState = MockWebSocket.CONNECTING;
        this._sentMessages = [];

        // Store instance for test access
        MockWebSocket._lastInstance = this;
        MockWebSocket._instances.push(this);
    }

    send(data) {
        if (this.readyState !== MockWebSocket.OPEN) {
            throw new Error('WebSocket is not open');
        }
        this._sentMessages.push(data);
    }

    close(code, reason) {
        this.readyState = MockWebSocket.CLOSED;
        this.emit('close', code, reason);
    }

    // ── Test helpers ──

    /** Simulate the server accepting the connection. */
    simulateOpen() {
        this.readyState = MockWebSocket.OPEN;
        this.emit('open');
    }

    /** Simulate receiving a message from the server. */
    simulateMessage(data) {
        this.emit('message', typeof data === 'string' ? data : JSON.stringify(data));
    }

    /** Simulate a connection error. */
    simulateError(err) {
        this.emit('error', err instanceof Error ? err : new Error(err));
    }

    /** Simulate server-side close. */
    simulateClose(code, reason) {
        this.readyState = MockWebSocket.CLOSED;
        this.emit('close', code, reason);
    }

    /** Get all messages sent by the client, parsed as JSON. */
    getSentMessages() {
        return this._sentMessages.map(m => JSON.parse(m));
    }

    /** Get the last message sent by the client, parsed as JSON. */
    getLastSentMessage() {
        if (this._sentMessages.length === 0) { return null; }
        return JSON.parse(this._sentMessages[this._sentMessages.length - 1]);
    }
}

// Static constants (match real ws module)
MockWebSocket.CONNECTING = 0;
MockWebSocket.OPEN = 1;
MockWebSocket.CLOSING = 2;
MockWebSocket.CLOSED = 3;

// Static tracking
MockWebSocket._lastInstance = null;
MockWebSocket._instances = [];

/** Reset all tracking between tests. */
MockWebSocket._reset = () => {
    MockWebSocket._lastInstance = null;
    MockWebSocket._instances = [];
};

module.exports = MockWebSocket;
module.exports.default = MockWebSocket;
