/**
 * Tests for ClarAItyCodeLensProvider.
 *
 * Coverage:
 * - addPendingChange(): fires onDidChangeCodeLenses, normalizes paths, overwrites same path
 * - removePendingChange(): removes by callId, fires event, safe when callId not found
 * - clear(): removes all pending changes, fires event
 * - provideCodeLenses(): returns Accept/Reject/ViewDiff lenses for pending files,
 *   empty array for non-pending, correct commands and arguments, case-insensitive matching,
 *   edit_file vs write_file tooltip distinction
 * - dispose(): disposes the internal EventEmitter
 *
 * Total: 25 tests across 5 describe blocks
 */

import * as vscode from 'vscode';
import { ClarAItyCodeLensProvider } from '../code-lens-provider';

/** Helper: create a mock TextDocument with a uri pointing to the given path. */
function mockDocument(filePath: string): vscode.TextDocument {
    return {
        uri: vscode.Uri.file(filePath),
    } as unknown as vscode.TextDocument;
}

describe('ClarAItyCodeLensProvider', () => {
    let provider: ClarAItyCodeLensProvider;

    beforeEach(() => {
        provider = new ClarAItyCodeLensProvider();
    });

    afterEach(() => {
        provider.dispose();
    });

    // ── addPendingChange() ──────────────────────────────────────────

    describe('addPendingChange()', () => {
        test('fires onDidChangeCodeLenses when a change is added', () => {
            const fired: void[] = [];
            provider.onDidChangeCodeLenses(() => fired.push(undefined));

            provider.addPendingChange('call-1', 'write_file', '/workspace/src/index.ts', { content: 'hello' });

            expect(fired).toHaveLength(1);
        });

        test('fires onDidChangeCodeLenses each time a change is added', () => {
            const fired: void[] = [];
            provider.onDidChangeCodeLenses(() => fired.push(undefined));

            provider.addPendingChange('call-1', 'write_file', '/workspace/a.ts', {});
            provider.addPendingChange('call-2', 'edit_file', '/workspace/b.ts', {});

            expect(fired).toHaveLength(2);
        });

        test('normalizes backslash paths to forward slashes and lowercases', () => {
            provider.addPendingChange('call-1', 'write_file', 'C:\\Users\\Dev\\Project\\File.ts', { content: 'data' });

            // The normalized key is "c:/users/dev/project/file.ts"
            // So a document with a path that normalizes to the same key should match
            const doc = mockDocument('C:\\Users\\Dev\\Project\\File.ts');
            const lenses = provider.provideCodeLenses(doc);

            expect(lenses).toHaveLength(3);
        });

        test('supports multiple changes for the same file path', () => {
            provider.addPendingChange('call-1', 'write_file', '/workspace/file.ts', { content: 'old' });
            provider.addPendingChange('call-2', 'edit_file', '/workspace/file.ts', { content: 'new' });

            const doc = mockDocument('/workspace/file.ts');
            const lenses = provider.provideCodeLenses(doc);

            // Should have 6 lenses (3 per change * 2 changes)
            expect(lenses).toHaveLength(6);
            expect(lenses[0].command!.arguments).toEqual(['call-1']);
            expect(lenses[3].command!.arguments).toEqual(['call-2']);
        });

        test('stores distinct changes for different paths', () => {
            provider.addPendingChange('call-1', 'write_file', '/workspace/a.ts', {});
            provider.addPendingChange('call-2', 'write_file', '/workspace/b.ts', {});

            const docA = mockDocument('/workspace/a.ts');
            const docB = mockDocument('/workspace/b.ts');

            expect(provider.provideCodeLenses(docA)).toHaveLength(3);
            expect(provider.provideCodeLenses(docB)).toHaveLength(3);
            expect(provider.provideCodeLenses(docA)[0].command!.arguments).toEqual(['call-1']);
            expect(provider.provideCodeLenses(docB)[0].command!.arguments).toEqual(['call-2']);
        });
    });

    // ── removePendingChange() ───────────────────────────────────────

    describe('removePendingChange()', () => {
        test('removes a pending change by callId', () => {
            provider.addPendingChange('call-1', 'write_file', '/workspace/file.ts', {});

            provider.removePendingChange('call-1');

            const doc = mockDocument('/workspace/file.ts');
            expect(provider.provideCodeLenses(doc)).toEqual([]);
        });

        test('fires onDidChangeCodeLenses when a change is removed', () => {
            provider.addPendingChange('call-1', 'write_file', '/workspace/file.ts', {});

            const fired: void[] = [];
            provider.onDidChangeCodeLenses(() => fired.push(undefined));

            provider.removePendingChange('call-1');

            expect(fired).toHaveLength(1);
        });

        test('fires onDidChangeCodeLenses even when callId is not found', () => {
            const fired: void[] = [];
            provider.onDidChangeCodeLenses(() => fired.push(undefined));

            provider.removePendingChange('nonexistent-call');

            // The implementation always fires the event
            expect(fired).toHaveLength(1);
        });

        test('does not crash when called with a nonexistent callId', () => {
            expect(() => {
                provider.removePendingChange('nonexistent-call');
            }).not.toThrow();
        });

        test('only removes the matching callId, leaving others intact', () => {
            provider.addPendingChange('call-1', 'write_file', '/workspace/a.ts', {});
            provider.addPendingChange('call-2', 'write_file', '/workspace/b.ts', {});

            provider.removePendingChange('call-1');

            const docA = mockDocument('/workspace/a.ts');
            const docB = mockDocument('/workspace/b.ts');
            expect(provider.provideCodeLenses(docA)).toEqual([]);
            expect(provider.provideCodeLenses(docB)).toHaveLength(3);
        });
    });

    // ── clear() ─────────────────────────────────────────────────────

    describe('clear()', () => {
        test('removes all pending changes', () => {
            provider.addPendingChange('call-1', 'write_file', '/workspace/a.ts', {});
            provider.addPendingChange('call-2', 'edit_file', '/workspace/b.ts', {});

            provider.clear();

            expect(provider.provideCodeLenses(mockDocument('/workspace/a.ts'))).toEqual([]);
            expect(provider.provideCodeLenses(mockDocument('/workspace/b.ts'))).toEqual([]);
        });

        test('fires onDidChangeCodeLenses', () => {
            provider.addPendingChange('call-1', 'write_file', '/workspace/file.ts', {});

            const fired: void[] = [];
            provider.onDidChangeCodeLenses(() => fired.push(undefined));

            provider.clear();

            expect(fired).toHaveLength(1);
        });

        test('does not crash when called on an already-empty provider', () => {
            expect(() => {
                provider.clear();
            }).not.toThrow();
        });

        test('fires event even when empty', () => {
            const fired: void[] = [];
            provider.onDidChangeCodeLenses(() => fired.push(undefined));

            provider.clear();

            // The implementation always fires
            expect(fired).toHaveLength(1);
        });
    });

    // ── provideCodeLenses() ─────────────────────────────────────────

    describe('provideCodeLenses()', () => {
        const sampleArgs = { content: 'console.log("hello");' };

        test('returns 3 CodeLens items for a pending file', () => {
            provider.addPendingChange('call-1', 'write_file', '/workspace/file.ts', sampleArgs);

            const doc = mockDocument('/workspace/file.ts');
            const lenses = provider.provideCodeLenses(doc);

            expect(lenses).toHaveLength(3);
        });

        test('returns empty array for a non-pending file', () => {
            provider.addPendingChange('call-1', 'write_file', '/workspace/file.ts', sampleArgs);

            const doc = mockDocument('/workspace/other.ts');
            const lenses = provider.provideCodeLenses(doc);

            expect(lenses).toEqual([]);
        });

        test('returns empty array when no changes are pending', () => {
            const doc = mockDocument('/workspace/file.ts');
            const lenses = provider.provideCodeLenses(doc);

            expect(lenses).toEqual([]);
        });

        test('Accept lens has correct command name, title, and arguments', () => {
            provider.addPendingChange('call-42', 'write_file', '/workspace/file.ts', sampleArgs);

            const doc = mockDocument('/workspace/file.ts');
            const lenses = provider.provideCodeLenses(doc);
            const accept = lenses[0];

            expect(accept).toBeInstanceOf(vscode.CodeLens);
            expect(accept.command!.title).toBe('$(check) Accept Change');
            expect(accept.command!.command).toBe('claraity.acceptChange');
            expect(accept.command!.arguments).toEqual(['call-42']);
        });

        test('Reject lens has correct command name, title, and arguments', () => {
            provider.addPendingChange('call-42', 'write_file', '/workspace/file.ts', sampleArgs);

            const doc = mockDocument('/workspace/file.ts');
            const lenses = provider.provideCodeLenses(doc);
            const reject = lenses[1];

            expect(reject).toBeInstanceOf(vscode.CodeLens);
            expect(reject.command!.title).toBe('$(close) Reject Change');
            expect(reject.command!.command).toBe('claraity.rejectChange');
            expect(reject.command!.arguments).toEqual(['call-42']);
            expect(reject.command!.tooltip).toBe('Reject the proposed change');
        });

        test('View Diff lens has correct command name, title, and arguments', () => {
            provider.addPendingChange('call-42', 'edit_file', '/workspace/file.ts', sampleArgs);

            const doc = mockDocument('/workspace/file.ts');
            const lenses = provider.provideCodeLenses(doc);
            const viewDiff = lenses[2];

            expect(viewDiff).toBeInstanceOf(vscode.CodeLens);
            expect(viewDiff.command!.title).toBe('$(diff) View Diff');
            expect(viewDiff.command!.command).toBe('claraity.viewDiff');
            expect(viewDiff.command!.arguments).toEqual(['call-42', 'edit_file', sampleArgs]);
            expect(viewDiff.command!.tooltip).toBe('Open diff view for this change');
        });

        test('all lenses share Range(0,0,0,0) at top of file', () => {
            provider.addPendingChange('call-1', 'write_file', '/workspace/file.ts', sampleArgs);

            const doc = mockDocument('/workspace/file.ts');
            const lenses = provider.provideCodeLenses(doc);

            for (const lens of lenses) {
                expect(lens.range.start).toEqual({ line: 0, character: 0 });
                expect(lens.range.end).toEqual({ line: 0, character: 0 });
            }
        });

        test('Accept tooltip says "edit" for edit_file tool', () => {
            provider.addPendingChange('call-1', 'edit_file', '/workspace/file.ts', sampleArgs);

            const doc = mockDocument('/workspace/file.ts');
            const lenses = provider.provideCodeLenses(doc);
            const accept = lenses[0];

            expect(accept.command!.tooltip).toBe('ClarAIty wants to edit this file');
        });

        test('Accept tooltip says "write" for write_file tool', () => {
            provider.addPendingChange('call-1', 'write_file', '/workspace/file.ts', sampleArgs);

            const doc = mockDocument('/workspace/file.ts');
            const lenses = provider.provideCodeLenses(doc);
            const accept = lenses[0];

            expect(accept.command!.tooltip).toBe('ClarAIty wants to write to this file');
        });

        test('case-insensitive path matching on Windows-style paths', () => {
            // Add with uppercase path
            provider.addPendingChange('call-1', 'write_file', 'C:\\Users\\Dev\\PROJECT\\File.ts', sampleArgs);

            // Query with different casing
            const doc = mockDocument('C:\\users\\dev\\project\\file.ts');
            const lenses = provider.provideCodeLenses(doc);

            expect(lenses).toHaveLength(3);
        });

        test('case-insensitive matching with forward-slash paths', () => {
            provider.addPendingChange('call-1', 'write_file', '/Workspace/SRC/Index.ts', sampleArgs);

            const doc = mockDocument('/workspace/src/index.ts');
            const lenses = provider.provideCodeLenses(doc);

            expect(lenses).toHaveLength(3);
        });

        test('returns empty array after the pending change is removed', () => {
            provider.addPendingChange('call-1', 'write_file', '/workspace/file.ts', sampleArgs);
            provider.removePendingChange('call-1');

            const doc = mockDocument('/workspace/file.ts');
            const lenses = provider.provideCodeLenses(doc);

            expect(lenses).toEqual([]);
        });

        test('returns empty array after clear()', () => {
            provider.addPendingChange('call-1', 'write_file', '/workspace/file.ts', sampleArgs);
            provider.clear();

            const doc = mockDocument('/workspace/file.ts');
            const lenses = provider.provideCodeLenses(doc);

            expect(lenses).toEqual([]);
        });
    });

    // ── dispose() ───────────────────────────────────────────────────

    describe('dispose()', () => {
        test('disposes the event emitter so listeners stop receiving events', () => {
            const fired: void[] = [];
            provider.onDidChangeCodeLenses(() => fired.push(undefined));

            provider.dispose();

            // After dispose, addPendingChange fires to no listeners
            provider.addPendingChange('call-1', 'write_file', '/workspace/file.ts', {});

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
