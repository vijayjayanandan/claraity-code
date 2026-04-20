/**
 * Comprehensive unit tests for python-env.ts
 *
 * Coverage:
 * - compareSemver(): equality, greater, less, different lengths, multi-digit
 * - checkDevMode(): source present and absent
 * - checkInstalledPackage(): successful version, error/not installed, empty stdout
 * - resolveBundledBinary(): binary found (flat/PyInstaller layout), not found
 * - resolveLaunchConfig(): all branches -- dev mode variants, bundled binary,
 *   pip fallback, nothing found
 */

import * as vscode from 'vscode';
import * as fs from 'fs';
import { execFile } from 'child_process';
import {
    compareSemver,
    checkDevMode,
    checkInstalledPackage,
    resolveBundledBinary,
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

/** Set up execFile so the next call (checkPython) succeeds. */
function mockPythonFound(): void {
    mockExecFileOnce(null, 'Python 3.11.0\n');
}

/** Set up execFile so the next call (checkPython) fails. */
function mockPythonNotFound(): void {
    mockExecFileOnce(new Error('ENOENT'));
}

const PYTHON = 'python3';
const WORKDIR = '/projects/claraity';
const EXT_PATH = '/extensions/claraity';

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

// ── resolveBundledBinary ────────────────────────────────────────────────────

describe('resolveBundledBinary', () => {
    test('returns path when flat layout binary exists', () => {
        // First candidate (flat layout) exists
        mockExistsSync.mockImplementation((p: string) =>
            p.endsWith('claraity-server') || p.endsWith('claraity-server.exe'),
        );

        const result = resolveBundledBinary('/ext/path');

        expect(result).not.toBeNull();
        expect(result).toContain('bin');
    });

    test('returns path when PyInstaller layout binary exists', () => {
        // Only second candidate (PyInstaller layout) exists
        let callCount = 0;
        mockExistsSync.mockImplementation(() => {
            callCount++;
            return callCount === 2; // Second candidate
        });

        const result = resolveBundledBinary('/ext/path');

        expect(result).not.toBeNull();
    });

    test('returns null when no binary found', () => {
        mockExistsSync.mockReturnValue(false);

        const result = resolveBundledBinary('/ext/path');

        expect(result).toBeNull();
    });
});

// ── resolveLaunchConfig ──────────────────────────────────────────────────────

describe('resolveLaunchConfig', () => {

    // -- Dev mode: devMode='always' with source + Python present --

    test('returns dev mode when devMode="always", source exists, Python available', async () => {
        // checkDevMode: source exists
        mockExistsSync.mockReturnValue(true);
        // checkPython: available
        mockPythonFound();

        const result = await resolveLaunchConfig(
            PYTHON, WORKDIR, 'always', EXT_PATH,
        );

        expect(result).not.toBeNull();
        expect(result!.mode).toBe('dev');
        expect(result!.command).toBe(PYTHON);
        expect(result!.args).toEqual(['-m', 'src.server']);
        expect(result!.cwd).toBe(WORKDIR);
    });

    // -- Dev mode: devMode='always' but no source --

    test('returns null when devMode="always" but source missing', async () => {
        mockExistsSync.mockReturnValue(false);

        const result = await resolveLaunchConfig(
            PYTHON, WORKDIR, 'always', EXT_PATH,
        );

        expect(result).toBeNull();
        expect(vscode.window.showErrorMessage).toHaveBeenCalledWith(
            expect.stringContaining('devMode is "always"'),
        );
    });

    // -- Dev mode: devMode='always', source exists but Python missing --

    test('returns null when devMode="always", source exists, but Python missing', async () => {
        // checkDevMode: source exists (first call), binary check (subsequent calls)
        mockExistsSync.mockReturnValue(true);
        // checkPython: not available
        mockPythonNotFound();

        const result = await resolveLaunchConfig(
            PYTHON, WORKDIR, 'always', EXT_PATH,
        );

        expect(result).toBeNull();
        expect(vscode.window.showErrorMessage).toHaveBeenCalledWith(
            expect.stringContaining('Dev mode requires Python'),
        );
    });

    // -- Dev mode: devMode='auto' with source + Python --

    test('returns dev mode when devMode="auto", source exists, Python available', async () => {
        mockExistsSync.mockReturnValue(true);
        mockPythonFound();

        const result = await resolveLaunchConfig(
            PYTHON, WORKDIR, 'auto', EXT_PATH,
        );

        expect(result).not.toBeNull();
        expect(result!.mode).toBe('dev');
    });

    // -- Dev mode: devMode='auto', source exists but Python missing, falls through to binary --

    test('falls through to bundled binary when devMode="auto", source exists, but Python missing', async () => {
        // checkDevMode needs __main__.py to exist, but binary check also uses existsSync
        const path = require('path');
        mockExistsSync.mockImplementation((p: string) => {
            if (p.includes('__main__.py')) { return true; }
            if (p.includes('bin')) { return true; } // bundled binary found
            return false;
        });
        mockPythonNotFound();

        const result = await resolveLaunchConfig(
            PYTHON, WORKDIR, 'auto', EXT_PATH,
        );

        expect(result).not.toBeNull();
        expect(result!.mode).toBe('bundled');
    });

    // -- Bundled binary: devMode='never' --

    test('returns bundled config when devMode="never" and binary exists', async () => {
        mockExistsSync.mockReturnValue(true);

        const result = await resolveLaunchConfig(
            PYTHON, WORKDIR, 'never', EXT_PATH,
        );

        expect(result).not.toBeNull();
        expect(result!.mode).toBe('bundled');
        expect(result!.args).toContain('--workdir');
        expect(result!.cwd).toBe(WORKDIR);
    });

    // -- Pip fallback: no binary, Python + package available --

    test('falls back to pip package when no binary and package installed', async () => {
        mockExistsSync.mockReturnValue(false); // no source, no binary
        mockPythonFound();
        mockExecFileOnce(null, '0.13.0\n'); // checkInstalledPackage

        const result = await resolveLaunchConfig(
            PYTHON, WORKDIR, 'never', EXT_PATH,
        );

        expect(result).not.toBeNull();
        expect(result!.mode).toBe('installed');
        expect(result!.version).toBe('0.13.0');
    });

    // -- Nothing found: no binary, no Python --

    test('returns null with reinstall message when nothing found', async () => {
        mockExistsSync.mockReturnValue(false); // no source, no binary
        mockPythonNotFound();

        const result = await resolveLaunchConfig(
            PYTHON, WORKDIR, 'never', EXT_PATH,
        );

        expect(result).toBeNull();
        expect(vscode.window.showErrorMessage).toHaveBeenCalledWith(
            expect.stringContaining('reinstall'),
        );
    });

    // -- Nothing found: no binary, Python available but no package --

    test('returns null when no binary and pip package not installed', async () => {
        mockExistsSync.mockReturnValue(false);
        mockPythonFound();
        mockExecFileOnce(new Error('not installed'));

        const result = await resolveLaunchConfig(
            PYTHON, WORKDIR, 'never', EXT_PATH,
        );

        expect(result).toBeNull();
        expect(vscode.window.showErrorMessage).toHaveBeenCalledWith(
            expect.stringContaining('reinstall'),
        );
    });

    // -- devMode='never' skips dev mode even if source exists --

    test('skips dev mode when devMode="never" even if source exists', async () => {
        // Source exists AND binary exists
        mockExistsSync.mockReturnValue(true);

        const result = await resolveLaunchConfig(
            PYTHON, WORKDIR, 'never', EXT_PATH,
        );

        expect(result).not.toBeNull();
        expect(result!.mode).toBe('bundled'); // Not dev
    });
});
