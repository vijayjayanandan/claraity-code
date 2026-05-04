/**
 * Server Launch Resolution
 *
 * Resolves how to launch the ClarAIty server:
 *   1. Dev mode       - explicit opt-in via devMode setting (python -m src.server)
 *   2. Bundled binary - claraity-server.exe shipped with the extension (no Python needed)
 *   3. Pip package    - claraity-code installed via pip (silent fallback, no prompts)
 */

import * as vscode from 'vscode';
import * as fs from 'fs';
import * as path from 'path';
import { execFile, execFileSync } from 'child_process';

// ── Types ──────────────────────────────────────────────────────────────────

export interface LaunchConfig {
    mode: 'bundled' | 'dev' | 'installed';
    command: string;
    args: string[];
    cwd: string;
    version?: string;
}

// ── Constants ──────────────────────────────────────────────────────────────

export const MIN_AGENT_VERSION = '1.1.0';
export const PYPI_PACKAGE = 'claraity-code';

// ── Main Orchestrator ──────────────────────────────────────────────────────

/**
 * Determine how to launch the ClarAIty server.
 *
 * Priority:
 *   1. Dev mode (devMode="always" or "auto" with source present) — requires Python
 *   2. Bundled binary (claraity-server.exe in extension bin/) — no Python needed
 *   3. Pip package (claraity-code installed) — silent fallback, no install prompts
 *
 * Returns null if no viable launch method is found.
 */
export async function resolveLaunchConfig(
    pythonPath: string,
    workDir: string,
    devMode: string,
    extensionPath: string,
    additionalFolders: string[] = [],
): Promise<LaunchConfig | null> {
    // Build --workspace-folders arg if multi-root workspace
    const wsArgs: string[] = [];
    if (additionalFolders.length > 0) {
        wsArgs.push('--workspace-folders', [workDir, ...additionalFolders].join(','));
    }

    // 1. Dev mode — only when explicitly requested
    if (devMode === 'always') {
        if (!checkDevMode(workDir)) {
            vscode.window.showErrorMessage(
                'ClarAIty: devMode is "always" but source files not found in workspace. ' +
                'Ensure src/server/__main__.py exists.',
            );
            return null;
        }
        const pythonOk = await checkPython(pythonPath);
        if (!pythonOk) {
            vscode.window.showErrorMessage(
                `ClarAIty: Dev mode requires Python. Python not found at "${pythonPath}". ` +
                'Set "claraity.pythonPath" in VS Code settings or switch devMode to "never".',
            );
            return null;
        }
        return {
            mode: 'dev',
            command: pythonPath,
            args: ['-m', 'src.server', ...wsArgs],
            cwd: workDir,
        };
    }

    if (devMode === 'auto' && checkDevMode(workDir)) {
        const pythonOk = await checkPython(pythonPath);
        if (pythonOk) {
            return {
                mode: 'dev',
                command: pythonPath,
                args: ['-m', 'src.server', ...wsArgs],
                cwd: workDir,
            };
        }
        // Python not available — fall through to bundled binary
    }

    // 2. Bundled binary — no Python needed
    const bundledPath = resolveBundledBinary(extensionPath);
    if (bundledPath) {
        return {
            mode: 'bundled',
            command: bundledPath,
            args: ['--workdir', workDir, ...wsArgs],
            cwd: workDir,
        };
    }

    // 3. Pip package — silent fallback (no install prompts)
    const pythonOk = await checkPython(pythonPath);
    if (pythonOk) {
        const installedVersion = await checkInstalledPackage(pythonPath);
        if (installedVersion) {
            return {
                mode: 'installed',
                command: pythonPath,
                args: ['-m', 'src.server', '--workdir', workDir, ...wsArgs],
                cwd: workDir,
                version: installedVersion,
            };
        }
    }

    // Nothing worked
    vscode.window.showErrorMessage(
        'ClarAIty: Server binary not found. Please reinstall the ClarAIty extension. ' +
        'If the issue persists, contact the team.',
    );
    return null;
}

// ── Helpers ────────────────────────────────────────────────────────────────

/** Check that the Python interpreter is callable. */
function checkPython(pythonPath: string): Promise<boolean> {
    return new Promise((resolve) => {
        execFile(pythonPath, ['--version'], { timeout: 10_000 }, (err) => {
            resolve(!err);
        });
    });
}

/** Return true if the workspace contains the server source entry point. */
export function checkDevMode(workDir: string): boolean {
    return fs.existsSync(path.join(workDir, 'src', 'server', '__main__.py'));
}

/**
 * Check for the bundled server binary in the extension's bin/ directory.
 * Supports both flat layout (bin/claraity-server.exe) and
 * PyInstaller one-folder layout (bin/claraity-server/claraity-server.exe).
 * Returns the binary path if found, null otherwise.
 */
export function resolveBundledBinary(extensionPath: string): string | null {
    const binaryName = process.platform === 'win32'
        ? 'claraity-server.exe'
        : 'claraity-server';

    const candidates = [
        path.join(extensionPath, 'bin', binaryName),
        path.join(extensionPath, 'bin', binaryName.replace(/\.exe$/, ''), binaryName),
    ];

    for (const binPath of candidates) {
        if (fs.existsSync(binPath)) {
            // Unix: restore execute permission (lost during VSIX ZIP packaging)
            if (process.platform !== 'win32') {
                try {
                    fs.chmodSync(binPath, 0o755);
                } catch {
                    // Best-effort — may fail on read-only filesystem
                }
            }
            // macOS: clear quarantine attribute set on downloaded binaries
            if (process.platform === 'darwin') {
                try {
                    execFileSync('xattr', ['-cr', path.dirname(binPath)], {
                        timeout: 30_000,
                        stdio: 'ignore',
                    });
                } catch {
                    // Attribute may not exist — ignore
                }
            }
            return binPath;
        }
    }
    return null;
}

/** Return the installed version of claraity-code, or null if not installed. */
export function checkInstalledPackage(pythonPath: string): Promise<string | null> {
    return new Promise((resolve) => {
        // Use --  separator and JSON-safe constant to prevent injection
        const script =
            `import importlib.metadata,sys,json; print(importlib.metadata.version(json.loads(sys.argv[1])))`;
        execFile(pythonPath, ['-c', script, JSON.stringify(PYPI_PACKAGE)], { timeout: 15_000 }, (err, stdout) => {
            if (err) {
                resolve(null);
                return;
            }
            const version = stdout.trim();
            resolve(version || null);
        });
    });
}

// ── Version Comparison ─────────────────────────────────────────────────────

/**
 * Simple semver comparison: split on '.', compare major/minor/patch numerically.
 * Returns negative if a < b, 0 if equal, positive if a > b.
 */
export function compareSemver(a: string, b: string): number {
    const pa = a.split('.').map(Number);
    const pb = b.split('.').map(Number);
    const len = Math.max(pa.length, pb.length);

    for (let i = 0; i < len; i++) {
        const va = pa[i] ?? 0;
        const vb = pb[i] ?? 0;
        if (va !== vb) {
            return va - vb;
        }
    }
    return 0;
}
