/**
 * Smoke test to verify Vitest infrastructure works with VS Code mock.
 */

import * as vscode from 'vscode';

describe('Vitest infrastructure', () => {
    test('vscode mock is loaded', () => {
        expect(vscode).toBeDefined();
        expect(vscode.window).toBeDefined();
        expect(vscode.workspace).toBeDefined();
    });

    test('EventEmitter works', () => {
        const emitter = new vscode.EventEmitter<string>();
        const received: string[] = [];
        emitter.event((data: string) => received.push(data));
        emitter.fire('hello');
        emitter.fire('world');
        expect(received).toEqual(['hello', 'world']);
        emitter.dispose();
    });

    test('Uri.file works', () => {
        const uri = vscode.Uri.file('/test/path');
        expect(uri.fsPath).toBe('/test/path');
    });

    test('window.createOutputChannel works', () => {
        const channel = vscode.window.createOutputChannel('test');
        channel.appendLine('test message');
        expect(channel.appendLine).toHaveBeenCalledWith('test message');
    });
});
