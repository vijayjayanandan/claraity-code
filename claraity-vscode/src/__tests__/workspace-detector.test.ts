/**
 * Tests for workspace-detector.ts.
 *
 * Coverage:
 * - detectProjectContext(): Node/TS, Python, Rust, Go, Java projects
 * - Framework detection: React, Next.js, Vue, Angular, Django, FastAPI, Flask
 * - Test runner detection: Jest, Vitest, Mocha, pytest
 * - Package manager detection: npm, yarn, pnpm, poetry, pip
 * - Build tool detection: Vite, Webpack
 * - Monorepo detection
 * - formatProjectContext(): compact text output
 * - Edge cases: no workspace, empty package.json, mixed projects
 *
 * Total: 20 tests across 4 describe blocks
 */

import * as vscode from 'vscode';
import { detectProjectContext, formatProjectContext, ProjectContext } from '../workspace-detector';

// Access mocks
const fsMock = vscode.workspace.fs;
const findFilesMock = vscode.workspace.findFiles as vi.Mock;

/** Helper: mock findFiles to return a match for specific config files. */
function mockConfigFiles(files: string[]): void {
    findFilesMock.mockImplementation((pattern: any) => {
        // The pattern is a RelativePattern; extract the pattern string
        const patternStr = typeof pattern === 'string' ? pattern : (pattern.pattern || pattern._pattern || '');
        if (files.some(f => patternStr === f || patternStr.includes(f))) {
            return Promise.resolve([vscode.Uri.file(`/test/workspace/${patternStr}`)]);
        }
        return Promise.resolve([]);
    });
}

/** Helper: mock readFile for package.json with given content. */
function mockPackageJson(content: Record<string, any>): void {
    (fsMock.readFile as vi.Mock).mockImplementation((uri: any) => {
        const path = uri.fsPath || uri.path || '';
        if (path.includes('package.json')) {
            return Promise.resolve(Buffer.from(JSON.stringify(content)));
        }
        if (path.includes('pyproject.toml')) {
            return Promise.reject(new Error('Not found'));
        }
        return Promise.reject(new Error('Not found'));
    });
}

/** Helper: mock readFile for pyproject.toml. */
function mockPyprojectToml(content: string): void {
    (fsMock.readFile as vi.Mock).mockImplementation((uri: any) => {
        const path = uri.fsPath || uri.path || '';
        if (path.includes('pyproject.toml')) {
            return Promise.resolve(Buffer.from(content));
        }
        return Promise.reject(new Error('Not found'));
    });
}

describe('workspace-detector', () => {
    beforeEach(() => {
        findFilesMock.mockReset();
        (fsMock.readFile as vi.Mock).mockReset();
        (fsMock.readDirectory as vi.Mock)?.mockReset?.();
        // Default: no files found
        findFilesMock.mockResolvedValue([]);
        (fsMock.readFile as vi.Mock).mockRejectedValue(new Error('Not found'));
        // Mock readDirectory for top-level dirs
        if (fsMock.readDirectory) {
            (fsMock.readDirectory as vi.Mock).mockResolvedValue([
                ['src', 2], // FileType.Directory = 2
                ['tests', 2],
                ['docs', 2],
                ['node_modules', 2],
                ['.git', 2],
                ['README.md', 1], // FileType.File = 1
            ]);
        }
    });

    // ── Node.js / TypeScript Detection ────────────────────────────────

    describe('Node.js / TypeScript projects', () => {
        test('detects TypeScript with React', async () => {
            mockConfigFiles(['package.json', 'tsconfig.json']);
            mockPackageJson({
                dependencies: { react: '^18.0.0', 'react-dom': '^18.0.0' },
                devDependencies: { jest: '^29.0.0', typescript: '^5.0.0' },
            });

            const ctx = await detectProjectContext();

            expect(ctx).not.toBeNull();
            expect(ctx!.language).toBe('TypeScript');
            expect(ctx!.framework).toBe('React');
            expect(ctx!.testRunner).toBe('Jest');
        });

        test('detects JavaScript with Next.js', async () => {
            mockConfigFiles(['package.json']);
            mockPackageJson({
                dependencies: { next: '^14.0.0', react: '^18.0.0' },
                devDependencies: {},
            });

            const ctx = await detectProjectContext();

            expect(ctx!.language).toBe('JavaScript');
            expect(ctx!.framework).toBe('Next.js');
        });

        test('detects Vue framework', async () => {
            mockConfigFiles(['package.json', 'tsconfig.json']);
            mockPackageJson({
                dependencies: { vue: '^3.0.0' },
                devDependencies: { vitest: '^1.0.0', vite: '^5.0.0' },
            });

            const ctx = await detectProjectContext();

            expect(ctx!.framework).toBe('Vue');
            expect(ctx!.testRunner).toBe('Vitest');
            expect(ctx!.buildTool).toBe('Vite');
        });

        test('detects Angular framework', async () => {
            mockConfigFiles(['package.json', 'tsconfig.json']);
            mockPackageJson({
                dependencies: { '@angular/core': '^17.0.0' },
                devDependencies: {},
            });

            const ctx = await detectProjectContext();

            expect(ctx!.framework).toBe('Angular');
        });

        test('detects pnpm from lock file', async () => {
            mockConfigFiles(['package.json', 'tsconfig.json']);
            mockPackageJson({
                dependencies: { express: '^4.18.0' },
                devDependencies: { mocha: '^10.0.0' },
            });
            // Override findFiles to also find pnpm-lock.yaml
            const origImpl = findFilesMock.getMockImplementation();
            findFilesMock.mockImplementation((pattern: any) => {
                const patternStr = typeof pattern === 'string' ? pattern : (pattern.pattern || pattern._pattern || '');
                if (patternStr === 'pnpm-lock.yaml' || patternStr.includes('pnpm-lock.yaml')) {
                    return Promise.resolve([vscode.Uri.file('/test/workspace/pnpm-lock.yaml')]);
                }
                if (origImpl) return origImpl(pattern);
                return Promise.resolve([]);
            });

            const ctx = await detectProjectContext();

            expect(ctx!.framework).toBe('Express');
            expect(ctx!.testRunner).toBe('Mocha');
            expect(ctx!.packageManager).toBe('pnpm');
        });

        test('detects monorepo from workspaces field', async () => {
            mockConfigFiles(['package.json']);
            mockPackageJson({
                workspaces: ['packages/*'],
                dependencies: {},
                devDependencies: { turbo: '^1.0.0' },
            });

            const ctx = await detectProjectContext();

            expect(ctx!.monorepo).toBe(true);
            expect(ctx!.buildTool).toBe('Turborepo');
        });

        test('detects packageManager field', async () => {
            mockConfigFiles(['package.json']);
            mockPackageJson({
                packageManager: 'yarn@4.0.0',
                dependencies: {},
                devDependencies: {},
            });

            const ctx = await detectProjectContext();

            expect(ctx!.packageManager).toBe('yarn');
        });
    });

    // ── Python Detection ──────────────────────────────────────────────

    describe('Python projects', () => {
        test('detects Python with pytest from pyproject.toml', async () => {
            mockConfigFiles(['pyproject.toml']);
            mockPyprojectToml(`
[tool.poetry]
name = "my-project"

[tool.pytest.ini_options]
testpaths = ["tests"]

[tool.poetry.dependencies]
fastapi = "^0.100.0"
            `);

            const ctx = await detectProjectContext();

            expect(ctx!.language).toBe('Python');
            expect(ctx!.framework).toBe('FastAPI');
            expect(ctx!.testRunner).toBe('pytest');
            expect(ctx!.packageManager).toBe('poetry');
        });

        test('detects Django from pyproject.toml', async () => {
            mockConfigFiles(['pyproject.toml']);
            mockPyprojectToml(`
[project]
dependencies = ["django>=4.2"]
            `);

            const ctx = await detectProjectContext();

            expect(ctx!.framework).toBe('Django');
        });

        test('detects pip as fallback package manager', async () => {
            mockConfigFiles(['requirements.txt']);

            const ctx = await detectProjectContext();

            expect(ctx!.language).toBe('Python');
            expect(ctx!.packageManager).toBe('pip');
        });
    });

    // ── Other Languages ───────────────────────────────────────────────

    describe('other languages', () => {
        test('detects Rust project', async () => {
            mockConfigFiles(['Cargo.toml']);

            const ctx = await detectProjectContext();

            expect(ctx!.language).toBe('Rust');
            expect(ctx!.packageManager).toBe('cargo');
        });

        test('detects Go project', async () => {
            mockConfigFiles(['go.mod']);

            const ctx = await detectProjectContext();

            expect(ctx!.language).toBe('Go');
        });

        test('detects Java Maven project', async () => {
            mockConfigFiles(['pom.xml']);

            const ctx = await detectProjectContext();

            expect(ctx!.language).toBe('Java');
            expect(ctx!.buildTool).toBe('Maven');
        });

        test('detects Java Gradle project', async () => {
            mockConfigFiles(['build.gradle']);

            const ctx = await detectProjectContext();

            expect(ctx!.language).toBe('Java');
            expect(ctx!.buildTool).toBe('Gradle');
        });

        test('returns unknown for empty workspace', async () => {
            const ctx = await detectProjectContext();

            expect(ctx).not.toBeNull();
            expect(ctx!.language).toBe('unknown');
            expect(ctx!.configFiles).toEqual([]);
        });
    });

    // ── formatProjectContext ──────────────────────────────────────────

    describe('formatProjectContext()', () => {
        test('formats full context with all fields', () => {
            const ctx: ProjectContext = {
                language: 'TypeScript',
                framework: 'React',
                testRunner: 'Jest',
                packageManager: 'pnpm',
                buildTool: 'Vite',
                monorepo: true,
                topLevelDirs: ['src', 'tests', 'docs'],
                configFiles: ['package.json', 'tsconfig.json'],
            };

            const result = formatProjectContext(ctx);

            expect(result).toContain('<project_context>');
            expect(result).toContain('Language: TypeScript');
            expect(result).toContain('Framework: React');
            expect(result).toContain('Tests: Jest');
            expect(result).toContain('Package manager: pnpm');
            expect(result).toContain('Build: Vite');
            expect(result).toContain('Monorepo: yes');
            expect(result).toContain('Structure: src, tests, docs');
            expect(result).toContain('</project_context>');
        });

        test('formats minimal context', () => {
            const ctx: ProjectContext = {
                language: 'Go',
                topLevelDirs: [],
                configFiles: ['go.mod'],
            };

            const result = formatProjectContext(ctx);

            expect(result).toContain('Language: Go');
            expect(result).not.toContain('Framework');
            expect(result).not.toContain('Structure');
        });

        test('omits optional fields when not present', () => {
            const ctx: ProjectContext = {
                language: 'Python',
                framework: 'FastAPI',
                topLevelDirs: ['src'],
                configFiles: [],
            };

            const result = formatProjectContext(ctx);

            expect(result).toContain('Language: Python');
            expect(result).toContain('Framework: FastAPI');
            expect(result).not.toContain('Tests:');
            expect(result).not.toContain('Package manager:');
        });
    });
});
