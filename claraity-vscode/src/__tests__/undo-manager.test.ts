/**
 * Tests for UndoManager.
 *
 * Coverage:
 * - beginCheckpoint(): starts a new checkpoint, resets snapshotted set
 * - snapshotFile(): reads file content, stores in checkpoint, deduplicates
 * - commitCheckpoint(): finalizes, returns checkpoint or null, trims history
 * - undo(): restores files, deletes new files, removes checkpoint and later ones
 * - getLastCheckpoint() / getAllCheckpoints(): accessors
 * - clear(): resets all state
 * - dispose(): alias for clear
 * - Edge cases: no checkpoint active, empty checkpoint, multiple turns
 *
 * Total: 25 tests across 6 describe blocks
 */

import * as vscode from 'vscode';
import { UndoManager, UndoCheckpoint } from '../undo-manager';

// Access the workspace fs mock
const fsMock = vscode.workspace.fs;

describe('UndoManager', () => {
    let manager: UndoManager;

    beforeEach(() => {
        manager = new UndoManager();
        // Reset fs mock defaults
        (fsMock.readFile as jest.Mock).mockReset();
        (fsMock.writeFile as jest.Mock).mockReset();
        (fsMock.delete as jest.Mock).mockReset();
        (fsMock.readFile as jest.Mock).mockRejectedValue(new Error('File not found'));
        (fsMock.writeFile as jest.Mock).mockResolvedValue(undefined);
        (fsMock.delete as jest.Mock).mockResolvedValue(undefined);
    });

    afterEach(() => {
        manager.dispose();
    });

    // ── beginCheckpoint() ────────────────────────────────────────────

    describe('beginCheckpoint()', () => {
        test('starts a new checkpoint with incrementing turnId', () => {
            manager.beginCheckpoint();
            // Can't directly inspect private fields, but commitCheckpoint
            // will return null if no files are snapshotted
            const cp = manager.commitCheckpoint();
            expect(cp).toBeNull(); // No files snapshotted
        });

        test('successive checkpoints get incrementing turn IDs', async () => {
            const fileContent = new Uint8Array([72, 101, 108, 108, 111]);
            (fsMock.readFile as jest.Mock).mockResolvedValue(fileContent);

            // Turn 1
            manager.beginCheckpoint();
            await manager.snapshotFile('/workspace/a.ts');
            const cp1 = manager.commitCheckpoint();

            // Turn 2
            manager.beginCheckpoint();
            await manager.snapshotFile('/workspace/b.ts');
            const cp2 = manager.commitCheckpoint();

            expect(cp1!.turnId).toBe('turn-1');
            expect(cp2!.turnId).toBe('turn-2');
        });

        test('replaces any uncommitted checkpoint', async () => {
            const fileContent = new Uint8Array([1, 2, 3]);
            (fsMock.readFile as jest.Mock).mockResolvedValue(fileContent);

            manager.beginCheckpoint();
            await manager.snapshotFile('/workspace/a.ts');
            // Don't commit — start a new one
            manager.beginCheckpoint();
            await manager.snapshotFile('/workspace/b.ts');
            const cp = manager.commitCheckpoint();

            expect(cp).not.toBeNull();
            expect(cp!.turnId).toBe('turn-2');
            // Only b.ts should be in checkpoint, not a.ts
            expect(cp!.files.size).toBe(1);
            const keys = Array.from(cp!.files.keys());
            expect(keys[0]).toContain('b.ts');
        });
    });

    // ── snapshotFile() ───────────────────────────────────────────────

    describe('snapshotFile()', () => {
        test('reads file content and stores snapshot', async () => {
            const fileContent = new Uint8Array([72, 101, 108, 108, 111]);
            (fsMock.readFile as jest.Mock).mockResolvedValue(fileContent);

            manager.beginCheckpoint();
            await manager.snapshotFile('/workspace/file.ts');

            expect(fsMock.readFile).toHaveBeenCalledTimes(1);

            const cp = manager.commitCheckpoint();
            expect(cp).not.toBeNull();
            expect(cp!.files.size).toBe(1);

            const snapshot = cp!.files.values().next().value;
            expect(snapshot!.path).toBe('/workspace/file.ts');
            expect(snapshot!.content).toEqual(fileContent);
        });

        test('stores null content for non-existent files (new file)', async () => {
            (fsMock.readFile as jest.Mock).mockRejectedValue(new Error('File not found'));

            manager.beginCheckpoint();
            await manager.snapshotFile('/workspace/new-file.ts');

            const cp = manager.commitCheckpoint();
            expect(cp).not.toBeNull();
            const snapshot = cp!.files.values().next().value;
            expect(snapshot!.content).toBeNull();
        });

        test('deduplicates snapshots for the same file in one turn', async () => {
            const fileContent = new Uint8Array([1, 2, 3]);
            (fsMock.readFile as jest.Mock).mockResolvedValue(fileContent);

            manager.beginCheckpoint();
            await manager.snapshotFile('/workspace/file.ts');
            await manager.snapshotFile('/workspace/file.ts');

            // readFile should only be called once
            expect(fsMock.readFile).toHaveBeenCalledTimes(1);
        });

        test('normalizes backslash paths for deduplication', async () => {
            const fileContent = new Uint8Array([1, 2, 3]);
            (fsMock.readFile as jest.Mock).mockResolvedValue(fileContent);

            manager.beginCheckpoint();
            await manager.snapshotFile('C:\\Users\\Dev\\file.ts');
            await manager.snapshotFile('c:/users/dev/file.ts');

            // Same file after normalization — only read once
            expect(fsMock.readFile).toHaveBeenCalledTimes(1);
        });

        test('snapshots multiple different files', async () => {
            const content1 = new Uint8Array([1]);
            const content2 = new Uint8Array([2]);
            (fsMock.readFile as jest.Mock)
                .mockResolvedValueOnce(content1)
                .mockResolvedValueOnce(content2);

            manager.beginCheckpoint();
            await manager.snapshotFile('/workspace/a.ts');
            await manager.snapshotFile('/workspace/b.ts');

            const cp = manager.commitCheckpoint();
            expect(cp!.files.size).toBe(2);
        });

        test('does nothing when no checkpoint is active', async () => {
            await manager.snapshotFile('/workspace/file.ts');
            expect(fsMock.readFile).not.toHaveBeenCalled();
        });
    });

    // ── commitCheckpoint() ───────────────────────────────────────────

    describe('commitCheckpoint()', () => {
        test('returns null when no files were snapshotted', () => {
            manager.beginCheckpoint();
            const cp = manager.commitCheckpoint();
            expect(cp).toBeNull();
        });

        test('returns null when no checkpoint was started', () => {
            const cp = manager.commitCheckpoint();
            expect(cp).toBeNull();
        });

        test('returns committed checkpoint with files', async () => {
            const fileContent = new Uint8Array([1, 2, 3]);
            (fsMock.readFile as jest.Mock).mockResolvedValue(fileContent);

            manager.beginCheckpoint();
            await manager.snapshotFile('/workspace/file.ts');
            const cp = manager.commitCheckpoint();

            expect(cp).not.toBeNull();
            expect(cp!.committed).toBe(true);
            expect(cp!.files.size).toBe(1);
            expect(cp!.timestamp).toBeLessThanOrEqual(Date.now());
        });

        test('trims history beyond MAX_HISTORY (10)', async () => {
            const fileContent = new Uint8Array([1]);
            (fsMock.readFile as jest.Mock).mockResolvedValue(fileContent);

            // Create 12 checkpoints
            for (let i = 0; i < 12; i++) {
                manager.beginCheckpoint();
                await manager.snapshotFile(`/workspace/file-${i}.ts`);
                manager.commitCheckpoint();
            }

            const all = manager.getAllCheckpoints();
            expect(all.length).toBe(10);
            // First two should have been trimmed
            expect(all[0].turnId).toBe('turn-3');
            expect(all[9].turnId).toBe('turn-12');
        });
    });

    // ── undo() ───────────────────────────────────────────────────────

    describe('undo()', () => {
        test('restores existing file to original content', async () => {
            const originalContent = new Uint8Array([1, 2, 3]);
            (fsMock.readFile as jest.Mock).mockResolvedValue(originalContent);

            manager.beginCheckpoint();
            await manager.snapshotFile('/workspace/file.ts');
            manager.commitCheckpoint();

            const restored = await manager.undo('turn-1');

            expect(restored).toEqual(['/workspace/file.ts']);
            expect(fsMock.writeFile).toHaveBeenCalledTimes(1);
            // Verify the content was written back
            const [uri, content] = (fsMock.writeFile as jest.Mock).mock.calls[0];
            expect(content).toEqual(originalContent);
        });

        test('deletes file that did not exist before', async () => {
            (fsMock.readFile as jest.Mock).mockRejectedValue(new Error('File not found'));

            manager.beginCheckpoint();
            await manager.snapshotFile('/workspace/new-file.ts');
            manager.commitCheckpoint();

            const restored = await manager.undo('turn-1');

            expect(restored).toEqual(['/workspace/new-file.ts']);
            expect(fsMock.delete).toHaveBeenCalledTimes(1);
        });

        test('restores multiple files in a single checkpoint', async () => {
            const content1 = new Uint8Array([1]);
            const content2 = new Uint8Array([2]);
            (fsMock.readFile as jest.Mock)
                .mockResolvedValueOnce(content1)
                .mockResolvedValueOnce(content2);

            manager.beginCheckpoint();
            await manager.snapshotFile('/workspace/a.ts');
            await manager.snapshotFile('/workspace/b.ts');
            manager.commitCheckpoint();

            const restored = await manager.undo('turn-1');

            expect(restored).toHaveLength(2);
            expect(fsMock.writeFile).toHaveBeenCalledTimes(2);
        });

        test('removes the undone checkpoint and all after it', async () => {
            const fileContent = new Uint8Array([1]);
            (fsMock.readFile as jest.Mock).mockResolvedValue(fileContent);

            // Create 3 checkpoints
            manager.beginCheckpoint();
            await manager.snapshotFile('/workspace/a.ts');
            manager.commitCheckpoint();

            manager.beginCheckpoint();
            await manager.snapshotFile('/workspace/b.ts');
            manager.commitCheckpoint();

            manager.beginCheckpoint();
            await manager.snapshotFile('/workspace/c.ts');
            manager.commitCheckpoint();

            expect(manager.getAllCheckpoints()).toHaveLength(3);

            // Undo turn-2 — should also remove turn-3
            await manager.undo('turn-2');

            const remaining = manager.getAllCheckpoints();
            expect(remaining).toHaveLength(1);
            expect(remaining[0].turnId).toBe('turn-1');
        });

        test('returns empty array for nonexistent turnId', async () => {
            const result = await manager.undo('nonexistent');
            expect(result).toEqual([]);
        });

        test('handles file restore errors gracefully', async () => {
            const fileContent = new Uint8Array([1, 2, 3]);
            (fsMock.readFile as jest.Mock).mockResolvedValue(fileContent);

            manager.beginCheckpoint();
            await manager.snapshotFile('/workspace/file.ts');
            manager.commitCheckpoint();

            // Make writeFile fail
            (fsMock.writeFile as jest.Mock).mockRejectedValue(new Error('Permission denied'));

            const restored = await manager.undo('turn-1');
            // File was not successfully restored
            expect(restored).toEqual([]);
        });
    });

    // ── Accessors ────────────────────────────────────────────────────

    describe('getLastCheckpoint() / getAllCheckpoints()', () => {
        test('getLastCheckpoint returns undefined when empty', () => {
            expect(manager.getLastCheckpoint()).toBeUndefined();
        });

        test('getLastCheckpoint returns the most recent', async () => {
            const fileContent = new Uint8Array([1]);
            (fsMock.readFile as jest.Mock).mockResolvedValue(fileContent);

            manager.beginCheckpoint();
            await manager.snapshotFile('/workspace/a.ts');
            manager.commitCheckpoint();

            manager.beginCheckpoint();
            await manager.snapshotFile('/workspace/b.ts');
            manager.commitCheckpoint();

            expect(manager.getLastCheckpoint()!.turnId).toBe('turn-2');
        });

        test('getAllCheckpoints returns a copy', async () => {
            const fileContent = new Uint8Array([1]);
            (fsMock.readFile as jest.Mock).mockResolvedValue(fileContent);

            manager.beginCheckpoint();
            await manager.snapshotFile('/workspace/a.ts');
            manager.commitCheckpoint();

            const all = manager.getAllCheckpoints();
            all.push({} as UndoCheckpoint); // Mutate copy

            expect(manager.getAllCheckpoints()).toHaveLength(1); // Original unaffected
        });
    });

    // ── clear() / dispose() ──────────────────────────────────────────

    describe('clear() / dispose()', () => {
        test('clear removes all checkpoints', async () => {
            const fileContent = new Uint8Array([1]);
            (fsMock.readFile as jest.Mock).mockResolvedValue(fileContent);

            manager.beginCheckpoint();
            await manager.snapshotFile('/workspace/a.ts');
            manager.commitCheckpoint();

            manager.clear();

            expect(manager.getAllCheckpoints()).toHaveLength(0);
            expect(manager.getLastCheckpoint()).toBeUndefined();
        });

        test('clear resets turn counter', async () => {
            const fileContent = new Uint8Array([1]);
            (fsMock.readFile as jest.Mock).mockResolvedValue(fileContent);

            manager.beginCheckpoint();
            await manager.snapshotFile('/workspace/a.ts');
            manager.commitCheckpoint();

            manager.clear();

            // After clear, next turn starts at turn-1 again
            manager.beginCheckpoint();
            await manager.snapshotFile('/workspace/b.ts');
            const cp = manager.commitCheckpoint();
            expect(cp!.turnId).toBe('turn-1');
        });

        test('dispose is an alias for clear', async () => {
            const fileContent = new Uint8Array([1]);
            (fsMock.readFile as jest.Mock).mockResolvedValue(fileContent);

            manager.beginCheckpoint();
            await manager.snapshotFile('/workspace/a.ts');
            manager.commitCheckpoint();

            manager.dispose();

            expect(manager.getAllCheckpoints()).toHaveLength(0);
        });

        test('clear cancels any active checkpoint', async () => {
            const fileContent = new Uint8Array([1]);
            (fsMock.readFile as jest.Mock).mockResolvedValue(fileContent);

            manager.beginCheckpoint();
            await manager.snapshotFile('/workspace/a.ts');
            // Don't commit

            manager.clear();

            // Commit should return null — active checkpoint was cleared
            const cp = manager.commitCheckpoint();
            expect(cp).toBeNull();
        });
    });
});
