/**
 * Python Environment Detection & Package Management
 *
 * Resolves how to launch the ClarAIty server:
 *   1. Dev mode  - source repo detected in workspace (python -m src.server)
 *   2. Installed - claraity-code package installed via pip
 *   3. Prompt    - offer to install the package
 */

import * as vscode from 'vscode';
import * as fs from 'fs';
import * as path from 'path';
import { execFile } from 'child_process';

// ── Types ──────────────────────────────────────────────────────────────────

export interface LaunchConfig {
    mode: 'dev' | 'installed';
    command: string;
    args: string[];
    cwd: string;
    version?: string;
}

// ── Constants ──────────────────────────────────────────────────────────────

export const MIN_AGENT_VERSION = '0.12.5';
export const PYPI_PACKAGE = 'claraity-code';

// ── Main Orchestrator ──────────────────────────────────────────────────────

/**
 * Determine how to launch the ClarAIty server.
 *
 * Priority: dev mode (source in workspace) > installed package > prompt install.
 * Returns null if no viable launch method is found.
 */
export async function resolveLaunchConfig(
    pythonPath: string,
    port: number,
    workDir: string,
    devMode: string,
    autoInstall: boolean,
): Promise<LaunchConfig | null> {
    // 1. Verify Python is available
    const pythonOk = await checkPython(pythonPath);
    if (!pythonOk) {
        vscode.window.showErrorMessage(
            `ClarAIty: Python not found at "${pythonPath}". ` +
            'Set "claraity.pythonPath" in VS Code settings.',
        );
        return null;
    }

    // 2. Dev mode check
    if (devMode === 'always' || (devMode === 'auto' && checkDevMode(workDir))) {
        if (devMode === 'always' && !checkDevMode(workDir)) {
            vscode.window.showErrorMessage(
                'ClarAIty: devMode is "always" but source files not found in workspace. ' +
                'Ensure src/server/__main__.py exists.',
            );
            return null;
        }
        return {
            mode: 'dev',
            command: pythonPath,
            args: ['-m', 'src.server'],
            cwd: workDir,
        };
    }

    // 3. Check installed package
    const installedVersion = await checkInstalledPackage(pythonPath);

    if (installedVersion) {
        if (compareSemver(installedVersion, MIN_AGENT_VERSION) >= 0) {
            // Installed and up to date
            return {
                mode: 'installed',
                command: pythonPath,
                args: ['-m', 'src.server', '--workdir', workDir],
                cwd: workDir,
                version: installedVersion,
            };
        }

        // Installed but outdated
        if (autoInstall) {
            const upgraded = await promptUpgrade(pythonPath, installedVersion);
            if (upgraded) {
                const newVersion = await checkInstalledPackage(pythonPath);
                return {
                    mode: 'installed',
                    command: pythonPath,
                    args: ['-m', 'src.server', '--workdir', workDir],
                    cwd: workDir,
                    version: newVersion ?? installedVersion,
                };
            }

            // User chose "Continue Anyway"
            return {
                mode: 'installed',
                command: pythonPath,
                args: ['-m', 'src.server', '--workdir', workDir],
                cwd: workDir,
                version: installedVersion,
            };
        }
    }

    // 4. Not installed -- prompt
    if (autoInstall) {
        const installed = await promptInstall(pythonPath);
        if (installed) {
            const newVersion = await checkInstalledPackage(pythonPath);
            if (newVersion) {
                return {
                    mode: 'installed',
                    command: pythonPath,
                    args: ['-m', 'src.server', '--workdir', workDir],
                    cwd: workDir,
                    version: newVersion,
                };
            }
        }
    }

    // Nothing worked
    if (!installedVersion) {
        vscode.window.showErrorMessage(
            `ClarAIty: The "${PYPI_PACKAGE}" package is not installed. ` +
            `Run: pip install ${PYPI_PACKAGE}`,
        );
    }
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

/**
 * Show a notification prompting the user to install the package.
 * Opens a terminal so the user can see pip output.
 * Returns true if the user confirmed a successful install via the Retry button.
 */
async function promptInstall(pythonPath: string): Promise<boolean> {
    const choice = await vscode.window.showInformationMessage(
        `ClarAIty: The "${PYPI_PACKAGE}" package is not installed.`,
        'Install',
        'Cancel',
    );

    if (choice !== 'Install') {
        return false;
    }

    return runPipInTerminal(pythonPath, 'install');
}

/**
 * Show a notification prompting the user to upgrade the package.
 * Returns true if the user chose to upgrade and confirmed success.
 * Returns false if the user chose "Continue Anyway" or "Cancel".
 */
async function promptUpgrade(
    pythonPath: string,
    currentVersion: string,
): Promise<boolean> {
    const choice = await vscode.window.showWarningMessage(
        `ClarAIty: Installed version ${currentVersion} is older than ` +
        `minimum ${MIN_AGENT_VERSION}.`,
        'Upgrade',
        'Continue Anyway',
        'Cancel',
    );

    if (choice === 'Continue Anyway' || choice === 'Cancel' || !choice) {
        return false;
    }

    return runPipInTerminal(pythonPath, 'upgrade');
}

/**
 * Run pip install/upgrade in a visible terminal and wait for user confirmation.
 */
async function runPipInTerminal(
    pythonPath: string,
    action: 'install' | 'upgrade',
): Promise<boolean> {
    const pipArgs = action === 'upgrade'
        ? `install --upgrade ${PYPI_PACKAGE}`
        : `install ${PYPI_PACKAGE}`;

    const terminal = vscode.window.createTerminal('ClarAIty Install');
    terminal.show();
    terminal.sendText(`${pythonPath} -m pip ${pipArgs}`);

    // Wait for user to confirm the install succeeded
    const retry = await vscode.window.showInformationMessage(
        `ClarAIty: Click "Retry" after pip finishes to continue.`,
        'Retry',
        'Cancel',
    );

    return retry === 'Retry';
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
