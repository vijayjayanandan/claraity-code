/**
 * Comprehensive unit tests for python-env.ts
 *
 * Coverage:
 * - compareSemver(): equality, greater, less, different lengths, multi-digit
 * - checkDevMode(): source present and absent
 * - checkInstalledPackage(): successful version, error/not installed, empty stdout
 * - resolveLaunchConfig(): all branches -- no python, dev mode variants,
 *   installed & up to date, outdated with upgrade, not installed with prompt, fallback null
 *
 * Total: 25+ tests covering all exported functions and their edge cases
 */

import * as vscode from 'vscode';
import * as fs from 'fs';
import { execFile } from 'child_process';
import {
    compareSemver,
    checkDevMode,
    checkInstalledPackage,
    resolveLaunchConfig,
    MIN_AGENT_VERSION,
    PYPI_PACKAGE,
    LaunchConfig,
} from '../python-env';

vi.mock('child_process');
vi.mock('fs');

// Type the mocked functions for convenience
const mockExecFile = execFile as unknown as vi.Mock;
const mockExistsSync = fs.existsSync as vi.Mock;

// ── Helpers ──────────────────────────────────────────────────────────────────

/**
 * Configure the execFile mock to invoke its callback with the given results.
 * Supports multiple sequential calls by pushing handlers onto a queue.
 */
function mockExecFileOnce(
    err: Error | null,
    stdout: string = '',
    stderr: string = '',
): void {
    mockExecFile.mockImplementationOnce(
        (_cmd: string, _args: string[], _opts: object, cb: Function) => {
            cb(err, stdout, stderr);
        },
    );
}

/**
 * Set up execFile so the first call (checkPython) succeeds.
 * Many resolveLaunchConfig tests need Python to be "found" first.
 */
function mockPythonFound(): void {
    mockExecFileOnce(null, 'Python 3.11.0\n');
}

/**
 * Set up execFile so the first call (checkPython) fails.
 */
function mockPythonNotFound(): void {
    mockExecFileOnce(new Error('ENOENT'));
}

// ── compareSemver ────────────────────────────────────────────────────────────

describe('compareSemver', () => {
    test('equal versions return 0', () => {
        expect(compareSemver('1.2.3', '1.2.3')).toBe(0);
    });

    test('equal single-segment versions return 0', () => {
        expect(compareSemver('5', '5')).toBe(0);
    });

    test('greater major version returns positive', () => {
        expect(compareSemver('2.0.0', '1.0.0')).toBeGreaterThan(0);
    });

    test('greater minor version returns positive', () => {
        expect(compareSemver('1.3.0', '1.2.0')).toBeGreaterThan(0);
    });

    test('greater patch version returns positive', () => {
        expect(compareSemver('1.2.4', '1.2.3')).toBeGreaterThan(0);
    });

    test('lesser major version returns negative', () => {
        expect(compareSemver('1.0.0', '2.0.0')).toBeLessThan(0);
    });

    test('lesser minor version returns negative', () => {
        expect(compareSemver('1.1.0', '1.2.0')).toBeLessThan(0);
    });

    test('lesser patch version returns negative', () => {
        expect(compareSemver('1.2.2', '1.2.3')).toBeLessThan(0);
    });

    test('different length versions treat missing segments as 0 (equal)', () => {
        expect(compareSemver('1.0', '1.0.0')).toBe(0);
    });

    test('different length versions where shorter is less', () => {
        expect(compareSemver('1.0', '1.0.1')).toBeLessThan(0);
    });

    test('different length versions where shorter is greater', () => {
        expect(compareSemver('1.1', '1.0.9')).toBeGreaterThan(0);
    });

    test('handles multi-digit version segments correctly', () => {
        // 12 > 9 numerically, but "12" < "9" lexicographically
        expect(compareSemver('1.12.0', '1.9.0')).toBeGreaterThan(0);
    });

    test('handles multi-digit patch segments correctly', () => {
        expect(compareSemver('0.1.100', '0.1.99')).toBeGreaterThan(0);
    });
});

// ── checkDevMode ─────────────────────────────────────────────────────────────

describe('checkDevMode', () => {
    test('returns true when src/server/__main__.py exists', () => {
        mockExistsSync.mockReturnValue(true);

        const result = checkDevMode('/my/workspace');

        expect(result).toBe(true);
        expect(mockExistsSync).toHaveBeenCalledWith(
            expect.stringContaining('__main__.py'),
        );
    });

    test('returns false when src/server/__main__.py does not exist', () => {
        mockExistsSync.mockReturnValue(false);

        const result = checkDevMode('/my/workspace');

        expect(result).toBe(false);
    });

    test('passes the correct joined path to existsSync', () => {
        mockExistsSync.mockReturnValue(false);
        const path = require('path');

        checkDevMode('/projects/claraity');

        const expectedPath = path.join(
            '/projects/claraity',
            'src',
            'server',
            '__main__.py',
        );
        expect(mockExistsSync).toHaveBeenCalledWith(expectedPath);
    });
});

// ── checkInstalledPackage ────────────────────────────────────────────────────

describe('checkInstalledPackage', () => {
    test('returns version string when package is installed', async () => {
        mockExecFileOnce(null, '0.13.0\n');

        const result = await checkInstalledPackage('python3');

        expect(result).toBe('0.13.0');
    });

    test('returns null on error (package not installed)', async () => {
        mockExecFileOnce(new Error('ModuleNotFoundError'));

        const result = await checkInstalledPackage('python3');

        expect(result).toBeNull();
    });

    test('returns null when stdout is empty string', async () => {
        mockExecFileOnce(null, '');

        const result = await checkInstalledPackage('python3');

        expect(result).toBeNull();
    });

    test('returns null when stdout is only whitespace', async () => {
        mockExecFileOnce(null, '   \n  ');

        const result = await checkInstalledPackage('python3');

        expect(result).toBeNull();
    });

    test('trims whitespace from version string', async () => {
        mockExecFileOnce(null, '  1.2.3  \n');

        const result = await checkInstalledPackage('python3');

        expect(result).toBe('1.2.3');
    });

    test('passes the correct python path and script to execFile', async () => {
        mockExecFileOnce(null, '1.0.0');

        await checkInstalledPackage('/usr/bin/python3');

        expect(mockExecFile).toHaveBeenCalledWith(
            '/usr/bin/python3',
            ['-c', expect.stringContaining('importlib.metadata'), JSON.stringify(PYPI_PACKAGE)],
            expect.objectContaining({ timeout: 15_000 }),
            expect.any(Function),
        );
    });
});

// ── resolveLaunchConfig ──────────────────────────────────────────────────────

describe('resolveLaunchConfig', () => {
    const PYTHON = 'python3';
    const PORT = 9120;
    const WORKDIR = '/projects/claraity';

    // -- Python not found --

    test('returns null and shows error when Python is not found', async () => {
        mockPythonNotFound();

        const result = await resolveLaunchConfig(
            PYTHON, PORT, WORKDIR, 'auto', true,
        );

        expect(result).toBeNull();
        expect(vscode.window.showErrorMessage).toHaveBeenCalledWith(
            expect.stringContaining('Python not found'),
        );
    });

    // -- Dev mode: devMode='always' with source present --

    test('returns dev mode config when devMode is "always" and source exists', async () => {
        mockPythonFound();
        mockExistsSync.mockReturnValue(true);

        const result = await resolveLaunchConfig(
            PYTHON, PORT, WORKDIR, 'always', false,
        );

        expect(result).not.toBeNull();
        expect(result!.mode).toBe('dev');
        expect(result!.command).toBe(PYTHON);
        expect(result!.args).toEqual(['-m', 'src.server']);
        expect(result!.cwd).toBe(WORKDIR);
    });

    // -- Dev mode: devMode='auto' with source present --

    test('returns dev mode config when devMode is "auto" and source exists', async () => {
        mockPythonFound();
        mockExistsSync.mockReturnValue(true);

        const result = await resolveLaunchConfig(
            PYTHON, PORT, WORKDIR, 'auto', false,
        );

        expect(result).not.toBeNull();
        expect(result!.mode).toBe('dev');
        expect(result!.args).toContain('-m');
        expect(result!.args).toContain('src.server');
    });

    // -- Dev mode: devMode='always' but no source --

    test('returns null and shows error when devMode is "always" but source is missing', async () => {
        mockPythonFound();
        mockExistsSync.mockReturnValue(false);

        const result = await resolveLaunchConfig(
            PYTHON, PORT, WORKDIR, 'always', false,
        );

        expect(result).toBeNull();
        expect(vscode.window.showErrorMessage).toHaveBeenCalledWith(
            expect.stringContaining('devMode is "always"'),
        );
    });

    // -- Dev mode: devMode='auto' but no source, falls through --

    test('falls through dev mode when devMode is "auto" and source is missing', async () => {
        mockPythonFound();
        mockExistsSync.mockReturnValue(false);
        // checkInstalledPackage call
        mockExecFileOnce(null, '0.13.0\n');

        const result = await resolveLaunchConfig(
            PYTHON, PORT, WORKDIR, 'auto', false,
        );

        // Should have fallen through to installed check
        expect(result).not.toBeNull();
        expect(result!.mode).toBe('installed');
    });

    // -- Installed and up to date --

    test('returns installed config when package is installed and up to date', async () => {
        mockPythonFound();
        mockExistsSync.mockReturnValue(false);
        // checkInstalledPackage returns a version >= MIN_AGENT_VERSION
        mockExecFileOnce(null, MIN_AGENT_VERSION + '\n');

        const result = await resolveLaunchConfig(
            PYTHON, PORT, WORKDIR, 'auto', true,
        );

        expect(result).not.toBeNull();
        expect(result!.mode).toBe('installed');
        expect(result!.command).toBe(PYTHON);
        expect(result!.args).toEqual([
            '-m', 'src.server', '--workdir', WORKDIR,
        ]);
        expect(result!.cwd).toBe(WORKDIR);
        expect(result!.version).toBe(MIN_AGENT_VERSION);
    });

    test('returns installed config with newer version', async () => {
        mockPythonFound();
        mockExistsSync.mockReturnValue(false);
        mockExecFileOnce(null, '99.0.0\n');

        const result = await resolveLaunchConfig(
            PYTHON, PORT, WORKDIR, 'never', true,
        );

        expect(result).not.toBeNull();
        expect(result!.mode).toBe('installed');
        expect(result!.version).toBe('99.0.0');
    });

    // -- Installed but outdated, user upgrades --

    test('handles outdated package - user upgrades successfully', async () => {
        mockPythonFound();
        mockExistsSync.mockReturnValue(false);
        // First checkInstalledPackage: outdated
        mockExecFileOnce(null, '0.1.0\n');
        // promptUpgrade: user clicks "Upgrade"
        (vscode.window.showWarningMessage as vi.Mock).mockResolvedValueOnce('Upgrade');
        // runPipInTerminal: user clicks "Retry"
        (vscode.window.showInformationMessage as vi.Mock).mockResolvedValueOnce('Retry');
        // Second checkInstalledPackage after upgrade
        mockExecFileOnce(null, '0.14.0\n');

        const result = await resolveLaunchConfig(
            PYTHON, PORT, WORKDIR, 'auto', true,
        );

        expect(result).not.toBeNull();
        expect(result!.mode).toBe('installed');
        expect(result!.version).toBe('0.14.0');
    });

    // -- Installed but outdated, user continues anyway --

    test('handles outdated package - user chooses "Continue Anyway"', async () => {
        mockPythonFound();
        mockExistsSync.mockReturnValue(false);
        // checkInstalledPackage: outdated
        mockExecFileOnce(null, '0.1.0\n');
        // promptUpgrade: user clicks "Continue Anyway"
        (vscode.window.showWarningMessage as vi.Mock).mockResolvedValueOnce('Continue Anyway');

        const result = await resolveLaunchConfig(
            PYTHON, PORT, WORKDIR, 'auto', true,
        );

        // Should still return an installed config with the old version
        expect(result).not.toBeNull();
        expect(result!.mode).toBe('installed');
        expect(result!.version).toBe('0.1.0');
    });

    // -- Not installed, user installs via prompt --

    test('handles not installed - user installs successfully', async () => {
        mockPythonFound();
        mockExistsSync.mockReturnValue(false);
        // checkInstalledPackage: not installed
        mockExecFileOnce(new Error('not installed'));
        // promptInstall: user clicks "Install"
        (vscode.window.showInformationMessage as vi.Mock)
            .mockResolvedValueOnce('Install')  // promptInstall choice
            .mockResolvedValueOnce('Retry');    // runPipInTerminal retry
        // checkInstalledPackage after install succeeds
        mockExecFileOnce(null, '0.13.0\n');

        const result = await resolveLaunchConfig(
            PYTHON, PORT, WORKDIR, 'auto', true,
        );

        expect(result).not.toBeNull();
        expect(result!.mode).toBe('installed');
        expect(result!.version).toBe('0.13.0');
    });

    // -- Not installed, user cancels install --

    test('returns null when not installed and user cancels install', async () => {
        mockPythonFound();
        mockExistsSync.mockReturnValue(false);
        // checkInstalledPackage: not installed
        mockExecFileOnce(new Error('not installed'));
        // promptInstall: user clicks "Cancel"
        (vscode.window.showInformationMessage as vi.Mock)
            .mockResolvedValueOnce('Cancel');

        const result = await resolveLaunchConfig(
            PYTHON, PORT, WORKDIR, 'auto', true,
        );

        expect(result).toBeNull();
        expect(vscode.window.showErrorMessage).toHaveBeenCalledWith(
            expect.stringContaining('not installed'),
        );
    });

    // -- Not installed, autoInstall=false --

    test('returns null when not installed and autoInstall is false', async () => {
        mockPythonFound();
        mockExistsSync.mockReturnValue(false);
        // checkInstalledPackage: not installed
        mockExecFileOnce(new Error('not installed'));

        const result = await resolveLaunchConfig(
            PYTHON, PORT, WORKDIR, 'auto', false,
        );

        expect(result).toBeNull();
        expect(vscode.window.showErrorMessage).toHaveBeenCalledWith(
            expect.stringContaining(PYPI_PACKAGE),
        );
    });

    // -- devMode='never' skips dev mode detection --

    test('skips dev mode when devMode is "never" even if source exists', async () => {
        mockPythonFound();
        // Source exists but devMode='never' should skip it
        mockExistsSync.mockReturnValue(true);
        // checkInstalledPackage returns good version
        mockExecFileOnce(null, MIN_AGENT_VERSION + '\n');

        const result = await resolveLaunchConfig(
            PYTHON, PORT, WORKDIR, 'never', false,
        );

        expect(result).not.toBeNull();
        expect(result!.mode).toBe('installed');
    });

    // -- Outdated package with autoInstall=false --

    test('returns null when package is outdated and autoInstall is false', async () => {
        mockPythonFound();
        mockExistsSync.mockReturnValue(false);
        // checkInstalledPackage: outdated version
        mockExecFileOnce(null, '0.1.0\n');

        const result = await resolveLaunchConfig(
            PYTHON, PORT, WORKDIR, 'auto', false,
        );

        // autoInstall=false means no upgrade prompt; installedVersion is truthy
        // so the "not installed" error branch is skipped, returns null
        expect(result).toBeNull();
    });

    // -- Install succeeds but version check fails afterward --

    test('returns null when install succeeds but version check returns null', async () => {
        mockPythonFound();
        mockExistsSync.mockReturnValue(false);
        // checkInstalledPackage: not installed
        mockExecFileOnce(new Error('not installed'));
        // promptInstall: user clicks "Install"
        (vscode.window.showInformationMessage as vi.Mock)
            .mockResolvedValueOnce('Install')
            .mockResolvedValueOnce('Retry');
        // checkInstalledPackage after install: still fails
        mockExecFileOnce(new Error('still broken'));

        const result = await resolveLaunchConfig(
            PYTHON, PORT, WORKDIR, 'auto', true,
        );

        // newVersion is null, so the inner if(newVersion) is false,
        // falls through to the "nothing worked" block
        expect(result).toBeNull();
    });
});
