/**
 * Undo manager for reverting agent-proposed file changes.
 *
 * Before each agent turn modifies files, it snapshots the current content.
 * After the turn, the user can click "Undo" to restore all files to their
 * pre-change state.
 *
 * Architecture:
 *   stream_start  → beginCheckpoint()
 *   tool_state_updated (awaiting_approval | running) → snapshotFile(path)
 *   stream_end    → commitCheckpoint() → returns checkpoint or null
 *   user clicks Undo → undo(turnId) → restores files
 */

import * as vscode from 'vscode';

export interface FileSnapshot {
    /** Original file path (as received from agent). */
    path: string;
    /** File content before the agent modified it. null = file did not exist. */
    content: Uint8Array | null;
}

export interface UndoCheckpoint {
    turnId: string;
    files: Map<string, FileSnapshot>;
    timestamp: number;
    committed: boolean;
}

const MAX_HISTORY = 10;

export class UndoManager {
    private checkpoints: UndoCheckpoint[] = [];
    private currentCheckpoint: UndoCheckpoint | null = null;
    private snapshotted = new Set<string>();
    private turnCounter = 0;
    private log?: vscode.OutputChannel;

    constructor(log?: vscode.OutputChannel) {
        this.log = log;
    }

    /** Start a new undo checkpoint for the current agent turn. */
    beginCheckpoint(): void {
        this.turnCounter++;
        this.currentCheckpoint = {
            turnId: `turn-${this.turnCounter}`,
            files: new Map(),
            timestamp: Date.now(),
            committed: false,
        };
        this.snapshotted.clear();
    }

    /**
     * Snapshot a file's current content before the agent modifies it.
     * Skips if already snapshotted in this turn or if no checkpoint is active.
     */
    async snapshotFile(filePath: string): Promise<void> {
        if (!this.currentCheckpoint) { return; }

        const normalized = filePath.replace(/\\/g, '/').toLowerCase();
        if (this.snapshotted.has(normalized)) { return; }
        this.snapshotted.add(normalized);

        try {
            const uri = vscode.Uri.file(filePath);
            const content = await vscode.workspace.fs.readFile(uri);
            this.currentCheckpoint.files.set(normalized, { path: filePath, content });
            this.log?.appendLine(`[Undo] Snapshotted: ${filePath}`);
        } catch {
            // File doesn't exist yet (new file creation)
            this.currentCheckpoint.files.set(normalized, { path: filePath, content: null });
            this.log?.appendLine(`[Undo] Snapshotted (new file): ${filePath}`);
        }
    }

    /**
     * Finalize the current checkpoint. Returns it if files were snapshotted,
     * or null if nothing was modified.
     */
    commitCheckpoint(): UndoCheckpoint | null {
        if (!this.currentCheckpoint || this.currentCheckpoint.files.size === 0) {
            this.currentCheckpoint = null;
            return null;
        }

        this.currentCheckpoint.committed = true;
        this.checkpoints.push(this.currentCheckpoint);

        // Trim oldest if over limit
        while (this.checkpoints.length > MAX_HISTORY) {
            this.checkpoints.shift();
        }

        const cp = this.currentCheckpoint;
        this.currentCheckpoint = null;
        return cp;
    }

    /** Get the most recent committed checkpoint. */
    getLastCheckpoint(): UndoCheckpoint | undefined {
        return this.checkpoints[this.checkpoints.length - 1];
    }

    /** Get all committed checkpoints (newest last). */
    getAllCheckpoints(): UndoCheckpoint[] {
        return [...this.checkpoints];
    }

    /**
     * Undo a checkpoint: restore all files to their pre-change state.
     * Returns the list of restored file paths.
     */
    async undo(turnId: string): Promise<string[]> {
        const idx = this.checkpoints.findIndex(c => c.turnId === turnId);
        if (idx < 0) { return []; }

        const checkpoint = this.checkpoints[idx];
        const restored: string[] = [];

        for (const [, snapshot] of checkpoint.files) {
            try {
                const uri = vscode.Uri.file(snapshot.path);
                if (snapshot.content === null) {
                    // File didn't exist before — remove it
                    await vscode.workspace.fs.delete(uri);
                } else {
                    await vscode.workspace.fs.writeFile(uri, snapshot.content);
                }
                restored.push(snapshot.path);
            } catch (err) {
                this.log?.appendLine(`[Undo] Failed to restore ${snapshot.path}: ${err}`);
            }
        }

        // Remove this checkpoint and everything after it
        this.checkpoints.splice(idx);
        this.log?.appendLine(`[Undo] Restored ${restored.length} file(s) from ${turnId}`);
        return restored;
    }

    /** Clear all checkpoints (e.g., on new session). */
    clear(): void {
        this.checkpoints = [];
        this.currentCheckpoint = null;
        this.snapshotted.clear();
        this.turnCounter = 0;
    }

    dispose(): void {
        this.clear();
    }
}
