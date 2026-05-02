/**
 * Comprehensive mock of the VS Code API for Vitest unit tests.
 *
 * This mock provides enough of the VS Code API surface for testing
 * extension.ts, agent-connection.ts, server-manager.ts, python-env.ts,
 * and sidebar-provider.ts without launching VS Code.
 */

// ── EventEmitter mock ──
class EventEmitter {
    constructor() {
        this._listeners = [];
    }
    get event() {
        const fn = (listener) => {
            this._listeners.push(listener);
            return { dispose: () => {
                const idx = this._listeners.indexOf(listener);
                if (idx >= 0) { this._listeners.splice(idx, 1); }
            }};
        };
        return fn;
    }
    fire(data) {
        for (const listener of this._listeners) {
            listener(data);
        }
    }
    dispose() {
        this._listeners = [];
    }
}

// ── CancellationTokenSource mock ──
class CancellationTokenSource {
    constructor() {
        this.token = { isCancellationRequested: false, onCancellationRequested: vi.fn() };
    }
    cancel() { this.token.isCancellationRequested = true; }
    dispose() {}
}

// ── Uri mock ──
const Uri = {
    file: (path) => ({
        fsPath: path,
        scheme: 'file',
        path: path.replace(/\\/g, '/'),
        toString: () => `file://${path.replace(/\\/g, '/')}`,
    }),
    parse: (str) => ({
        fsPath: str,
        scheme: str.split(':')[0] || 'file',
        path: str.replace(/^[^:]+:\/?\/?/, '/').split('?')[0],
        query: str.includes('?') ? str.split('?')[1] : '',
        toString: () => str,
    }),
    joinPath: (base, ...segments) => {
        const joined = [base.fsPath || base.path || '', ...segments].join('/');
        return {
            fsPath: joined,
            scheme: 'file',
            path: joined,
            toString: () => `file://${joined}`,
        };
    },
};

// ── Disposable mock ──
class Disposable {
    constructor(callOnDispose) {
        this._callOnDispose = callOnDispose;
    }
    static from(...disposables) {
        return new Disposable(() => {
            for (const d of disposables) { d.dispose(); }
        });
    }
    dispose() {
        if (this._callOnDispose) { this._callOnDispose(); }
    }
}

// ── StatusBarItem mock ──
function createStatusBarItem(alignment, priority) {
    return {
        alignment,
        priority,
        text: '',
        tooltip: '',
        command: undefined,
        show: vi.fn(),
        hide: vi.fn(),
        dispose: vi.fn(),
    };
}

// ── OutputChannel mock ──
function createOutputChannel(name) {
    return {
        name,
        append: vi.fn(),
        appendLine: vi.fn(),
        clear: vi.fn(),
        show: vi.fn(),
        hide: vi.fn(),
        dispose: vi.fn(),
    };
}

// ── Terminal mock ──
function createTerminal(name) {
    return {
        name,
        show: vi.fn(),
        sendText: vi.fn(),
        dispose: vi.fn(),
    };
}

// ── FileType enum mock ──
const FileType = { Unknown: 0, File: 1, Directory: 2, SymbolicLink: 64 };

// ── Workspace FS mock ──
const workspaceFs = {
    readFile: vi.fn().mockRejectedValue(new Error('File not found')),
    writeFile: vi.fn().mockResolvedValue(undefined),
    stat: vi.fn().mockRejectedValue(new Error('File not found')),
    delete: vi.fn().mockResolvedValue(undefined),
    readDirectory: vi.fn().mockResolvedValue([]),
};

// ── Configuration mock ──
const configValues = {};
function createConfig() {
    return {
        get: vi.fn((key, defaultValue) => {
            return configValues[key] !== undefined ? configValues[key] : defaultValue;
        }),
        update: vi.fn().mockResolvedValue(undefined),
        has: vi.fn((key) => key in configValues),
        inspect: vi.fn(() => undefined),
    };
}

// Helper to set config values in tests
function _setConfigValue(key, value) {
    configValues[key] = value;
}
function _clearConfig() {
    for (const key of Object.keys(configValues)) {
        delete configValues[key];
    }
}

// ── The main vscode module export ──
const vscode = {
    // Enums
    StatusBarAlignment: { Left: 1, Right: 2 },
    ViewColumn: { One: 1, Two: 2, Three: 3 },
    DiagnosticSeverity: { Error: 0, Warning: 1, Information: 2, Hint: 3 },
    ConfigurationTarget: { Global: 1, Workspace: 2, WorkspaceFolder: 3 },
    FileType,

    // Classes
    EventEmitter,
    CancellationTokenSource,
    Disposable,
    Uri,
    ThemeColor: class ThemeColor {
        constructor(id) { this.id = id; }
    },
    Range: class Range {
        constructor(startLine, startChar, endLine, endChar) {
            this.start = { line: startLine, character: startChar };
            this.end = { line: endLine, character: endChar };
        }
    },
    CodeLens: class CodeLens {
        constructor(range, command) {
            this.range = range;
            this.command = command;
        }
    },
    RelativePattern: class RelativePattern {
        constructor(base, pattern) {
            this.base = base;
            this.pattern = pattern;
            this._pattern = pattern;
        }
    },

    // Window
    window: {
        showInformationMessage: vi.fn().mockResolvedValue(undefined),
        showWarningMessage: vi.fn().mockResolvedValue(undefined),
        showErrorMessage: vi.fn().mockResolvedValue(undefined),
        createStatusBarItem: vi.fn(createStatusBarItem),
        createOutputChannel: vi.fn(createOutputChannel),
        createTerminal: vi.fn(createTerminal),
        registerWebviewViewProvider: vi.fn(() => new Disposable(() => {})),
        registerFileDecorationProvider: vi.fn(() => new Disposable(() => {})),
        activeTextEditor: undefined,
        showTextDocument: vi.fn().mockResolvedValue(undefined),
        terminals: [],
    },

    // Workspace
    workspace: {
        getConfiguration: vi.fn(() => createConfig()),
        workspaceFolders: [{ uri: Uri.file('/test/workspace'), name: 'test', index: 0 }],
        onDidChangeConfiguration: vi.fn(() => new Disposable(() => {})),
        onDidChangeWorkspaceFolders: vi.fn(() => new Disposable(() => {})),
        registerTextDocumentContentProvider: vi.fn(() => new Disposable(() => {})),
        findFiles: vi.fn().mockResolvedValue([]),
        fs: workspaceFs,
    },

    // Commands
    commands: {
        registerCommand: vi.fn((id, callback) => new Disposable(() => {})),
        executeCommand: vi.fn().mockResolvedValue(undefined),
    },

    // Environment
    env: {
        clipboard: {
            writeText: vi.fn().mockResolvedValue(undefined),
            readText: vi.fn().mockResolvedValue(''),
        },
        uriScheme: 'vscode',
    },

    // Languages
    languages: {
        registerCodeLensProvider: vi.fn(() => new Disposable(() => {})),
        registerHoverProvider: vi.fn(() => new Disposable(() => {})),
    },

    // Extensions
    extensions: {
        getExtension: vi.fn(() => undefined),
    },

    // Test helpers (not part of real API)
    _setConfigValue,
    _clearConfig,
};

module.exports = vscode;
