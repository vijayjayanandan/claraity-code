/**
 * JSON-RPC 2.0 envelope utilities for the stdio transport.
 *
 * Provides thin wrap/unwrap functions that convert between the internal
 * message format ({ type: 'X', ... }) and JSON-RPC 2.0 notifications
 * ({ jsonrpc: '2.0', method: 'X', params: { ... } }).
 *
 * Only the transport layer (stdio-connection.ts) calls these functions.
 * Everything above (sidebar-provider, types) continues to work with
 * the internal { type: ... } message format.
 */

const JSONRPC_VERSION = '2.0';

/**
 * Wrap an internal message as a JSON-RPC 2.0 notification.
 *
 * { type: 'text_delta', content: 'hi' }
 * -> { jsonrpc: '2.0', method: 'text_delta', params: { content: 'hi' } }
 */
export function wrapNotification(data: Record<string, any>): Record<string, any> {
    const { type, ...params } = data;
    const msg: Record<string, any> = { jsonrpc: JSONRPC_VERSION, method: type ?? 'unknown' };
    if (Object.keys(params).length > 0) {
        msg.params = params;
    }
    return msg;
}

/**
 * Unwrap a JSON-RPC 2.0 message to the internal format.
 *
 * { jsonrpc: '2.0', method: 'chat_message', params: { content: 'hi' } }
 * -> { type: 'chat_message', content: 'hi' }
 */
export function unwrapMessage(raw: Record<string, any>): Record<string, any> {
    const method = raw.method ?? 'unknown';
    const params = raw.params ?? {};
    return { type: method, ...params };
}

/**
 * Check whether a parsed object is a JSON-RPC 2.0 envelope.
 */
export function isJsonRpc(raw: Record<string, any>): boolean {
    return raw.jsonrpc === JSONRPC_VERSION;
}
