/**
 * Workspace detector for automatic project context.
 *
 * Scans the workspace root for config files (package.json, pyproject.toml,
 * Cargo.toml, go.mod, etc.) and builds a compact project summary that
 * gets sent with the first chat message so the agent understands the
 * project from the start.
 *
 * Detection covers:
 *   - Language & runtime (TypeScript, Python, Rust, Go, Java, C#)
 *   - Framework (React, Vue, Angular, Next.js, Django, Flask, FastAPI, etc.)
 *   - Test runner (Jest, Pytest, Vitest, Mocha, etc.)
 *   - Package manager (npm, yarn, pnpm, pip, poetry, cargo)
 *   - Build tools (webpack, vite, esbuild, tsc)
 *   - Monorepo detection (nx, lerna, turborepo, workspaces)
 *   - File structure summary (top-level dirs)
 */

import * as vscode from 'vscode';

export interface ProjectContext {
    language: string;
    framework?: string;
    testRunner?: string;
    packageManager?: string;
    buildTool?: string;
    monorepo?: boolean;
    topLevelDirs: string[];
    configFiles: string[];
}

/** Config files to look for, in order of priority. */
const CONFIG_FILES = [
    'package.json',
    'tsconfig.json',
    'pyproject.toml',
    'setup.py',
    'requirements.txt',
    'Cargo.toml',
    'go.mod',
    'pom.xml',
    'build.gradle',
    'build.gradle.kts',
    'Gemfile',
    'mix.exs',
    'CMakeLists.txt',
    'Makefile',
    '.csproj',
    'composer.json',
    'Dockerfile',
    'docker-compose.yml',
    '.github/workflows',
];

/**
 * Detect project context from workspace files.
 * Returns null if no workspace is open.
 */
export async function detectProjectContext(): Promise<ProjectContext | null> {
    const workDir = vscode.workspace.workspaceFolders?.[0]?.uri;
    if (!workDir) { return null; }

    const context: ProjectContext = {
        language: 'unknown',
        topLevelDirs: [],
        configFiles: [],
    };

    // Find which config files exist
    for (const configFile of CONFIG_FILES) {
        try {
            const pattern = new vscode.RelativePattern(workDir, configFile);
            const found = await vscode.workspace.findFiles(pattern, '**/node_modules/**', 1);
            if (found.length > 0) {
                context.configFiles.push(configFile);
            }
        } catch {
            // Skip files that can't be searched
        }
    }

    // Detect language and details from config files
    if (context.configFiles.includes('package.json')) {
        await detectNodeProject(workDir, context);
    }
    if (context.configFiles.includes('pyproject.toml') ||
        context.configFiles.includes('setup.py') ||
        context.configFiles.includes('requirements.txt')) {
        await detectPythonProject(workDir, context);
    }
    if (context.configFiles.includes('Cargo.toml')) {
        context.language = 'Rust';
        context.packageManager = 'cargo';
    }
    if (context.configFiles.includes('go.mod')) {
        context.language = 'Go';
    }
    if (context.configFiles.includes('pom.xml') || context.configFiles.includes('build.gradle') || context.configFiles.includes('build.gradle.kts')) {
        context.language = 'Java';
        context.buildTool = context.configFiles.includes('pom.xml') ? 'Maven' : 'Gradle';
    }

    // Get top-level directory names for structure overview
    try {
        const entries = await vscode.workspace.fs.readDirectory(workDir);
        context.topLevelDirs = entries
            .filter(([, type]) => type === vscode.FileType.Directory)
            .map(([name]) => name)
            .filter(name => !name.startsWith('.') && name !== 'node_modules' && name !== '__pycache__' && name !== 'venv' && name !== '.venv')
            .sort()
            .slice(0, 20); // Cap at 20 dirs
    } catch {
        // Ignore errors reading directory
    }

    return context;
}

async function detectNodeProject(workDir: vscode.Uri, context: ProjectContext): Promise<void> {
    context.language = context.configFiles.includes('tsconfig.json') ? 'TypeScript' : 'JavaScript';

    try {
        const pkgUri = vscode.Uri.joinPath(workDir, 'package.json');
        const bytes = await vscode.workspace.fs.readFile(pkgUri);
        const pkg = JSON.parse(Buffer.from(bytes).toString('utf-8'));
        const allDeps = { ...pkg.dependencies, ...pkg.devDependencies };

        // Framework detection
        if (allDeps.next) { context.framework = 'Next.js'; }
        else if (allDeps.react) { context.framework = 'React'; }
        else if (allDeps.vue) { context.framework = 'Vue'; }
        else if (allDeps['@angular/core']) { context.framework = 'Angular'; }
        else if (allDeps.svelte) { context.framework = 'Svelte'; }
        else if (allDeps.express) { context.framework = 'Express'; }
        else if (allDeps.fastify) { context.framework = 'Fastify'; }
        else if (allDeps.nuxt) { context.framework = 'Nuxt'; }
        else if (allDeps.remix) { context.framework = 'Remix'; }
        else if (allDeps.astro) { context.framework = 'Astro'; }

        // Test runner detection
        if (allDeps.jest || allDeps['ts-jest']) { context.testRunner = 'Jest'; }
        else if (allDeps.vitest) { context.testRunner = 'Vitest'; }
        else if (allDeps.mocha) { context.testRunner = 'Mocha'; }
        else if (allDeps['@playwright/test']) { context.testRunner = 'Playwright'; }
        else if (allDeps.cypress) { context.testRunner = 'Cypress'; }

        // Build tool detection
        if (allDeps.vite) { context.buildTool = 'Vite'; }
        else if (allDeps.webpack) { context.buildTool = 'Webpack'; }
        else if (allDeps.esbuild) { context.buildTool = 'esbuild'; }
        else if (allDeps.rollup) { context.buildTool = 'Rollup'; }
        else if (allDeps.turbo) { context.buildTool = 'Turborepo'; }

        // Package manager detection
        if (pkg.packageManager) {
            const pm = pkg.packageManager.split('@')[0];
            context.packageManager = pm;
        } else {
            // Check for lock files
            const lockFiles = [
                { file: 'pnpm-lock.yaml', pm: 'pnpm' },
                { file: 'yarn.lock', pm: 'yarn' },
                { file: 'bun.lockb', pm: 'bun' },
                { file: 'package-lock.json', pm: 'npm' },
            ];
            for (const { file, pm } of lockFiles) {
                try {
                    const found = await vscode.workspace.findFiles(
                        new vscode.RelativePattern(workDir, file), null, 1
                    );
                    if (found.length > 0) {
                        context.packageManager = pm;
                        break;
                    }
                } catch { /* skip */ }
            }
            if (!context.packageManager) { context.packageManager = 'npm'; }
        }

        // Monorepo detection
        if (pkg.workspaces || allDeps.lerna || allDeps.nx || allDeps.turbo) {
            context.monorepo = true;
        }
    } catch {
        // Failed to read package.json
    }
}

async function detectPythonProject(workDir: vscode.Uri, context: ProjectContext): Promise<void> {
    // Don't overwrite if already detected as Node (could be a full-stack project)
    if (context.language === 'unknown') {
        context.language = 'Python';
    }

    try {
        const pyprojectUri = vscode.Uri.joinPath(workDir, 'pyproject.toml');
        const bytes = await vscode.workspace.fs.readFile(pyprojectUri);
        const content = Buffer.from(bytes).toString('utf-8');

        // Framework detection from pyproject.toml content
        if (content.includes('django')) { context.framework = context.framework || 'Django'; }
        else if (content.includes('fastapi')) { context.framework = context.framework || 'FastAPI'; }
        else if (content.includes('flask')) { context.framework = context.framework || 'Flask'; }
        else if (content.includes('streamlit')) { context.framework = context.framework || 'Streamlit'; }

        // Test runner
        if (content.includes('[tool.pytest')) { context.testRunner = context.testRunner || 'pytest'; }

        // Package manager
        if (content.includes('[tool.poetry')) { context.packageManager = context.packageManager || 'poetry'; }
        else if (content.includes('[tool.pdm')) { context.packageManager = context.packageManager || 'pdm'; }
        else if (content.includes('[tool.uv')) { context.packageManager = context.packageManager || 'uv'; }
        else { context.packageManager = context.packageManager || 'pip'; }
    } catch {
        // No pyproject.toml or failed to read — fallback
        context.packageManager = context.packageManager || 'pip';
    }
}

/**
 * Format the detected project context into a compact text block
 * suitable for prepending to the first chat message.
 */
export function formatProjectContext(ctx: ProjectContext): string {
    const parts: string[] = [];

    parts.push(`Language: ${ctx.language}`);
    if (ctx.framework) { parts.push(`Framework: ${ctx.framework}`); }
    if (ctx.testRunner) { parts.push(`Tests: ${ctx.testRunner}`); }
    if (ctx.packageManager) { parts.push(`Package manager: ${ctx.packageManager}`); }
    if (ctx.buildTool) { parts.push(`Build: ${ctx.buildTool}`); }
    if (ctx.monorepo) { parts.push(`Monorepo: yes`); }
    if (ctx.topLevelDirs.length > 0) {
        parts.push(`Structure: ${ctx.topLevelDirs.join(', ')}`);
    }

    return `<project_context>\n${parts.join('\n')}\n</project_context>`;
}
