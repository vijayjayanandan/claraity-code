/**
 * Comprehensive mock of the VS Code API for Jest unit tests.
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
        this.token = { isCancellationRequested: false, onCancellationRequested: jest.fn() };
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
        show: jest.fn(),
        hide: jest.fn(),
        dispose: jest.fn(),
    };
}

// ── OutputChannel mock ──
function createOutputChannel(name) {
    return {
        name,
        append: jest.fn(),
        appendLine: jest.fn(),
        clear: jest.fn(),
        show: jest.fn(),
        hide: jest.fn(),
        dispose: jest.fn(),
    };
}

// ── Terminal mock ──
function createTerminal(name) {
    return {
        name,
        show: jest.fn(),
        sendText: jest.fn(),
        dispose: jest.fn(),
    };
}

// ── FileType enum mock ──
const FileType = { Unknown: 0, File: 1, Directory: 2, SymbolicLink: 64 };

// ── Workspace FS mock ──
const workspaceFs = {
    readFile: jest.fn().mockRejectedValue(new Error('File not found')),
    writeFile: jest.fn().mockResolvedValue(undefined),
    stat: jest.fn().mockRejectedValue(new Error('File not found')),
    delete: jest.fn().mockResolvedValue(undefined),
    readDirectory: jest.fn().mockResolvedValue([]),
};

// ── Configuration mock ──
const configValues = {};
function createConfig() {
    return {
        get: jest.fn((key, defaultValue) => {
            return configValues[key] !== undefined ? configValues[key] : defaultValue;
        }),
        update: jest.fn().mockResolvedValue(undefined),
        has: jest.fn((key) => key in configValues),
        inspect: jest.fn(() => undefined),
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
        showInformationMessage: jest.fn().mockResolvedValue(undefined),
        showWarningMessage: jest.fn().mockResolvedValue(undefined),
        showErrorMessage: jest.fn().mockResolvedValue(undefined),
        createStatusBarItem: jest.fn(createStatusBarItem),
        createOutputChannel: jest.fn(createOutputChannel),
        createTerminal: jest.fn(createTerminal),
        registerWebviewViewProvider: jest.fn(() => new Disposable(() => {})),
        registerFileDecorationProvider: jest.fn(() => new Disposable(() => {})),
        activeTextEditor: undefined,
        showTextDocument: jest.fn().mockResolvedValue(undefined),
        terminals: [],
    },

    // Workspace
    workspace: {
        getConfiguration: jest.fn(() => createConfig()),
        workspaceFolders: [{ uri: Uri.file('/test/workspace'), name: 'test', index: 0 }],
        onDidChangeConfiguration: jest.fn(() => new Disposable(() => {})),
        registerTextDocumentContentProvider: jest.fn(() => new Disposable(() => {})),
        findFiles: jest.fn().mockResolvedValue([]),
        fs: workspaceFs,
    },

    // Commands
    commands: {
        registerCommand: jest.fn((id, callback) => new Disposable(() => {})),
        executeCommand: jest.fn().mockResolvedValue(undefined),
    },

    // Environment
    env: {
        clipboard: {
            writeText: jest.fn().mockResolvedValue(undefined),
            readText: jest.fn().mockResolvedValue(''),
        },
        uriScheme: 'vscode',
    },

    // Languages
    languages: {
        registerCodeLensProvider: jest.fn(() => new Disposable(() => {})),
        registerHoverProvider: jest.fn(() => new Disposable(() => {})),
    },

    // Extensions
    extensions: {
        getExtension: jest.fn(() => undefined),
    },

    // Test helpers (not part of real API)
    _setConfigValue,
    _clearConfig,
};

module.exports = vscode;
