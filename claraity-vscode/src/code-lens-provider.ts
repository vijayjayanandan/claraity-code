/**
 * CodeLensProvider for inline accept/reject of agent-proposed file changes.
 *
 * When the agent proposes a write_file or edit_file operation and it requires
 * approval, this provider shows "Accept Change" and "Reject Change" lenses
 * at the top of the target file in the editor.
 */

import * as vscode from 'vscode';

interface PendingChange {
    callId: string;
    toolName: string;
    filePath: string;
    normalizedPath: string;
    args: Record<string, any>;
}

export class ClarAItyCodeLensProvider implements vscode.CodeLensProvider {
    private pendingChanges = new Map<string, PendingChange>(); // callId -> change
    private _onDidChangeCodeLenses = new vscode.EventEmitter<void>();
    readonly onDidChangeCodeLenses = this._onDidChangeCodeLenses.event;

    /**
     * Register a pending file change that needs approval.
     * Shows CodeLens in the editor for the target file.
     */
    addPendingChange(callId: string, toolName: string, filePath: string, args: Record<string, any>): void {
        const normalizedPath = filePath.replace(/\\/g, '/').toLowerCase();
        this.pendingChanges.set(callId, { callId, toolName, filePath, normalizedPath, args });
        this._onDidChangeCodeLenses.fire();
    }

    /**
     * Remove a pending change (after approval/rejection).
     */
    removePendingChange(callId: string): void {
        this.pendingChanges.delete(callId);
        this._onDidChangeCodeLenses.fire();
    }

    /**
     * Clear all pending changes (e.g., on new session).
     */
    clear(): void {
        this.pendingChanges.clear();
        this._onDidChangeCodeLenses.fire();
    }

    provideCodeLenses(document: vscode.TextDocument): vscode.CodeLens[] {
        const normalized = document.uri.fsPath.replace(/\\/g, '/').toLowerCase();

        // Find all pending changes targeting this file
        const matches: PendingChange[] = [];
        for (const change of this.pendingChanges.values()) {
            if (change.normalizedPath === normalized) {
                matches.push(change);
            }
        }

        if (matches.length === 0) {
            return [];
        }

        // Show lenses at the top of the file (line 0) for each pending change
        const lenses: vscode.CodeLens[] = [];
        for (const change of matches) {
            const range = new vscode.Range(0, 0, 0, 0);
            const summary = change.toolName === 'edit_file'
                ? 'ClarAIty wants to edit this file'
                : 'ClarAIty wants to write to this file';

            lenses.push(
                new vscode.CodeLens(range, {
                    title: '$(check) Accept Change',
                    command: 'claraity.acceptChange',
                    arguments: [change.callId],
                    tooltip: summary,
                }),
                new vscode.CodeLens(range, {
                    title: '$(close) Reject Change',
                    command: 'claraity.rejectChange',
                    arguments: [change.callId],
                    tooltip: 'Reject the proposed change',
                }),
                new vscode.CodeLens(range, {
                    title: '$(diff) View Diff',
                    command: 'claraity.viewDiff',
                    arguments: [change.callId, change.toolName, change.args],
                    tooltip: 'Open diff view for this change',
                }),
            );
        }
        return lenses;
    }

    dispose(): void {
        this._onDidChangeCodeLenses.dispose();
    }
}
