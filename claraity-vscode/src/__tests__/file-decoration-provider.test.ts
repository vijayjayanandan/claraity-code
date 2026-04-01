/**
 * Tests for ClarAItyFileDecorationProvider.
 *
 * Coverage:
 * - markModified(): event firing, path normalization, deduplication
 * - provideFileDecoration(): decoration for marked files, undefined for unmarked, Windows paths
 * - clear(): removes all decorations, fires event, safe on empty
 * - dispose(): disposes the internal EventEmitter
 */

import * as vscode from 'vscode';
import { ClarAItyFileDecorationProvider } from '../file-decoration-provider';

describe('ClarAItyFileDecorationProvider', () => {
    let provider: ClarAItyFileDecorationProvider;

    beforeEach(() => {
        provider = new ClarAItyFileDecorationProvider();
    });

    afterEach(() => {
        provider.dispose();
    });

    // ── markModified() ──────────────────────────────────────────────

    describe('markModified()', () => {
        test('fires onDidChangeFileDecorations with the file URI', () => {
            const fired: (vscode.Uri | vscode.Uri[] | undefined)[] = [];
            provider.onDidChangeFileDecorations((data) => fired.push(data));

            provider.markModified('/workspace/src/index.ts');

            expect(fired).toHaveLength(1);
            // The mock Uri.file returns an object with fsPath equal to the input
            expect((fired[0] as vscode.Uri).fsPath).toBe('/workspace/src/index.ts');
        });

        test('normalizes backslash path separators to forward slashes internally', () => {
            provider.markModified('C:\\Users\\dev\\project\\file.ts');

            // After normalization the file should be retrievable via provideFileDecoration
            // The mock Uri.file preserves the original fsPath, but provideFileDecoration
            // normalizes it again before lookup.
            const uri = vscode.Uri.file('C:\\Users\\dev\\project\\file.ts');
            const decoration = provider.provideFileDecoration(uri);

            expect(decoration).toBeDefined();
            expect(decoration!.badge).toBe('AI');
        });

        test('does not fire event when the same path is marked twice', () => {
            const fired: (vscode.Uri | vscode.Uri[] | undefined)[] = [];
            provider.onDidChangeFileDecorations((data) => fired.push(data));

            provider.markModified('/workspace/src/app.ts');
            provider.markModified('/workspace/src/app.ts');

            expect(fired).toHaveLength(1);
        });

        test('does not fire event when same path with different separators is marked twice', () => {
            const fired: (vscode.Uri | vscode.Uri[] | undefined)[] = [];
            provider.onDidChangeFileDecorations((data) => fired.push(data));

            // Both should normalize to the same internal key
            provider.markModified('C:\\project\\file.ts');
            provider.markModified('C:/project/file.ts');

            expect(fired).toHaveLength(1);
        });

        test('fires separate events for distinct files', () => {
            const fired: (vscode.Uri | vscode.Uri[] | undefined)[] = [];
            provider.onDidChangeFileDecorations((data) => fired.push(data));

            provider.markModified('/workspace/a.ts');
            provider.markModified('/workspace/b.ts');

            expect(fired).toHaveLength(2);
            expect((fired[0] as vscode.Uri).fsPath).toBe('/workspace/a.ts');
            expect((fired[1] as vscode.Uri).fsPath).toBe('/workspace/b.ts');
        });
    });

    // ── provideFileDecoration() ─────────────────────────────────────

    describe('provideFileDecoration()', () => {
        test('returns decoration with badge, tooltip, and color for a marked file', () => {
            provider.markModified('/workspace/src/index.ts');

            const uri = vscode.Uri.file('/workspace/src/index.ts');
            const decoration = provider.provideFileDecoration(uri);

            expect(decoration).toBeDefined();
            expect(decoration!.badge).toBe('AI');
            expect(decoration!.tooltip).toBe('Modified by ClarAIty');
            expect(decoration!.color).toBeInstanceOf(vscode.ThemeColor);
            expect((decoration!.color as vscode.ThemeColor).id).toBe('gitDecoration.addedResourceForeground');
        });

        test('returns undefined for an unmarked file', () => {
            const uri = vscode.Uri.file('/workspace/src/other.ts');
            const decoration = provider.provideFileDecoration(uri);

            expect(decoration).toBeUndefined();
        });

        test('returns undefined after file is cleared', () => {
            provider.markModified('/workspace/src/index.ts');
            provider.clear();

            const uri = vscode.Uri.file('/workspace/src/index.ts');
            const decoration = provider.provideFileDecoration(uri);

            expect(decoration).toBeUndefined();
        });

        test('handles Windows-style backslash paths in the URI', () => {
            // Mark with forward slashes (already normalized)
            provider.markModified('C:/Users/dev/project/file.ts');

            // Query with a URI whose fsPath uses backslashes (Windows behavior)
            const uri = vscode.Uri.file('C:\\Users\\dev\\project\\file.ts');
            const decoration = provider.provideFileDecoration(uri);

            expect(decoration).toBeDefined();
            expect(decoration!.badge).toBe('AI');
        });

        test('handles marking with backslashes and querying with forward slashes', () => {
            provider.markModified('C:\\Users\\dev\\project\\file.ts');

            const uri = vscode.Uri.file('C:/Users/dev/project/file.ts');
            const decoration = provider.provideFileDecoration(uri);

            expect(decoration).toBeDefined();
            expect(decoration!.badge).toBe('AI');
        });
    });

    // ── clear() ─────────────────────────────────────────────────────

    describe('clear()', () => {
        test('removes all decorations so provideFileDecoration returns undefined', () => {
            provider.markModified('/workspace/a.ts');
            provider.markModified('/workspace/b.ts');
            provider.clear();

            expect(provider.provideFileDecoration(vscode.Uri.file('/workspace/a.ts'))).toBeUndefined();
            expect(provider.provideFileDecoration(vscode.Uri.file('/workspace/b.ts'))).toBeUndefined();
        });

        test('fires event with array of all previously-marked URIs', () => {
            provider.markModified('/workspace/a.ts');
            provider.markModified('/workspace/b.ts');

            const fired: (vscode.Uri | vscode.Uri[] | undefined)[] = [];
            provider.onDidChangeFileDecorations((data) => fired.push(data));

            provider.clear();

            expect(fired).toHaveLength(1);
            const uris = fired[0] as vscode.Uri[];
            expect(Array.isArray(uris)).toBe(true);
            expect(uris).toHaveLength(2);

            // The cleared URIs should correspond to the normalized paths
            const fsPaths = uris.map((u) => u.fsPath);
            expect(fsPaths).toContain('/workspace/a.ts');
            expect(fsPaths).toContain('/workspace/b.ts');
        });

        test('does not fire event when there are no decorations to clear', () => {
            const fired: (vscode.Uri | vscode.Uri[] | undefined)[] = [];
            provider.onDidChangeFileDecorations((data) => fired.push(data));

            provider.clear();

            expect(fired).toHaveLength(0);
        });

        test('does not crash when called multiple times', () => {
            provider.markModified('/workspace/a.ts');

            expect(() => {
                provider.clear();
                provider.clear();
            }).not.toThrow();
        });

        test('allows re-marking files after clear', () => {
            provider.markModified('/workspace/a.ts');
            provider.clear();

            const fired: (vscode.Uri | vscode.Uri[] | undefined)[] = [];
            provider.onDidChangeFileDecorations((data) => fired.push(data));

            provider.markModified('/workspace/a.ts');

            // Should fire again since it was cleared
            expect(fired).toHaveLength(1);
            const decoration = provider.provideFileDecoration(vscode.Uri.file('/workspace/a.ts'));
            expect(decoration).toBeDefined();
            expect(decoration!.badge).toBe('AI');
        });
    });

    // ── dispose() ───────────────────────────────────────────────────

    describe('dispose()', () => {
        test('disposes the event emitter so listeners stop receiving events', () => {
            const fired: (vscode.Uri | vscode.Uri[] | undefined)[] = [];
            provider.onDidChangeFileDecorations((data) => fired.push(data));

            provider.dispose();

            // After dispose, markModified still adds to the set but fire goes to no listeners
            provider.markModified('/workspace/a.ts');

            expect(fired).toHaveLength(0);
        });

        test('does not crash when called multiple times', () => {
            expect(() => {
                provider.dispose();
                provider.dispose();
            }).not.toThrow();
        });
    });
});
