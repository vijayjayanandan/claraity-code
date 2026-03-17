/**
 * FileDecorationProvider for ClarAIty-modified files.
 *
 * Shows a badge and color on files in the VS Code explorer tree
 * that were modified by the agent during the current session.
 */

import * as vscode from 'vscode';

/** Normalize path for comparison: forward slashes + lowercase on Windows only. */
function normalizePath(p: string): string {
    const fwd = p.replace(/\\/g, '/');
    return process.platform === 'win32' ? fwd.toLowerCase() : fwd;
}

export class ClarAItyFileDecorationProvider implements vscode.FileDecorationProvider {
    private modifiedFiles = new Set<string>();

    private _onDidChangeFileDecorations = new vscode.EventEmitter<vscode.Uri | vscode.Uri[] | undefined>();
    readonly onDidChangeFileDecorations = this._onDidChangeFileDecorations.event;

    /**
     * Mark a file as modified by the agent.
     * Fires a decoration change so the explorer updates.
     */
    markModified(filePath: string): void {
        // Normalize path separators
        const normalized = normalizePath(filePath);
        if (this.modifiedFiles.has(normalized)) {
            return;
        }
        this.modifiedFiles.add(normalized);
        const uri = vscode.Uri.file(filePath);
        this._onDidChangeFileDecorations.fire(uri);
    }

    /**
     * Clear all decorations (e.g., on new session).
     */
    clear(): void {
        const uris = Array.from(this.modifiedFiles).map(p => vscode.Uri.file(p));
        this.modifiedFiles.clear();
        if (uris.length > 0) {
            this._onDidChangeFileDecorations.fire(uris);
        }
    }

    /**
     * Returns the decoration for a given file URI.
     * Called by VS Code when rendering the file tree.
     */
    provideFileDecoration(uri: vscode.Uri): vscode.FileDecoration | undefined {
        const normalized = normalizePath(uri.fsPath);
        if (this.modifiedFiles.has(normalized)) {
            return {
                badge: 'AI',
                tooltip: 'Modified by ClarAIty',
                color: new vscode.ThemeColor('gitDecoration.addedResourceForeground'),
            };
        }
        return undefined;
    }

    dispose(): void {
        this._onDidChangeFileDecorations.dispose();
    }
}
