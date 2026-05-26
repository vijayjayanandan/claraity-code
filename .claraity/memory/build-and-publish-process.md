---
name: Build and Publish Process
description: Full build pipeline - CI multi-platform builds, unified versioning (v1.0.0+), local dev builds, marketplace publish
type: reference
---

## Versioning (unified as of v1.0.0, 2026-04-25)

Single version across all sources. Previously repo tags, pyproject.toml, and package.json had independent versions that drifted (v0.19.0 / 0.14.1 / 0.9.0). Unified to 1.0.0.

**On release, bump all four:**
- `claraity-vscode/package.json` → `"version"`
- `pyproject.toml` → `version`
- `claraity-vscode/src/python-env.ts` → `MIN_AGENT_VERSION`
- Git tag (`v1.X.0`)

## Dependency Version Sync

When bumping package versions, update **both** files — they declare the same version floors independently:
- `requirements.txt` — local dev install
- `pyproject.toml` `[project].dependencies` — CI builds (`pip install .`)

`claraity-server.spec` lists **module names** only (not versions) for PyInstaller hidden imports. Only update it when **adding or removing** a package, not when bumping versions.

**ALWAYS update `claraity-server.spec` when:**
- Adding a new `src.*` module (e.g. `src.llm.openai_native_backend`, `src.llm.backend_factory`) -- PyInstaller cannot discover modules that are lazy-imported (local imports inside functions). Every new source module used in the server path must be explicitly listed under `hiddenimports`.
- Adding a new third-party package or using a new submodule of an existing package (e.g. `openai.resources.responses`).
- Upgrading an SDK that adds new submodules used at runtime.

**Rule:** Any time a new Python file is created under `src/`, ask: "Is this reachable from `src.server.__main__`?" If yes, add it to `claraity-server.spec`. When in doubt, add it -- a redundant entry is harmless, a missing one causes `ImportError` in the bundled binary.

## CI Multi-Platform Build (production releases)

Workflow: `.github/workflows/build-vsix.yml`

PyInstaller cannot cross-compile — it bundles native OS libraries from the build machine. Each platform builds on its own runner.

| Runner | Target | Binary |
|--------|--------|--------|
| `windows-latest` | `win32-x64` | `claraity-server.exe` |
| `macos-13` | `darwin-x64` | `claraity-server` (Intel) |
| `macos-14` | `darwin-arm64` | `claraity-server` (Apple Silicon) |
| `ubuntu-latest` | `linux-x64` | `claraity-server` |

**Triggers:**
- **Tag push (`v*`):** Builds all 4 platforms + publishes to marketplace
- **Manual (`workflow_dispatch`):** Builds all 4, publish optional (checkbox)

**Requires:** `VSCE_PAT` secret in GitHub repo settings.

Platform-targeted VSIXes (`vsce package --target`) — marketplace auto-serves correct binary per OS. ~31 MB each.

### macOS-specific handling in `python-env.ts`
- `chmod 755` — restores execute permission lost during VSIX ZIP packaging
- `xattr -cr` — clears macOS Gatekeeper quarantine attribute on downloaded binaries

## Local Dev Build (Windows only)

MUST use `.venv-build` (not global Python with 561+ packages):

```bash
cd C:/Vijay/Learning/AI/ai-coding-agent
.venv-build/Scripts/python.exe -m PyInstaller claraity-server.spec --noconfirm
cp -r dist/claraity-server/* claraity-vscode/bin/
```

~60s with `.venv-build`, 10+ minutes with global env. Windows binary only.

## VS Code Extension Build (local, single-platform)

```bash
cd claraity-vscode/webview-ui && npm run build    # Webview (React/Vite)
cd claraity-vscode && npm run compile              # Extension (esbuild)
cd claraity-vscode && npx vsce package --no-dependencies  # VSIX (no --target for local)
```

- Publisher: `claraity.claraity-code`
- Marketplace URL: https://marketplace.visualstudio.com/items?itemName=claraity.claraity-code
- VSIX includes: bin/ (Python binary), out/ (extension JS), webview-ui/dist/

## Full Release Sequence

1. Run tests
2. Commit changes
3. Bump version in `package.json`, `pyproject.toml`, `python-env.ts` MIN_AGENT_VERSION
4. Commit version bump
5. `git tag -a v1.X.0 -m "description"`
6. `git push origin main --tags`
7. CI auto-builds 4 platforms + publishes to marketplace

## Key Details

- Publisher: `claraity.claraity-code`
- Remote: `github.com-personal:vijayjayanandan/claraity-code.git`
- `python-env.ts` auto-fixes Unix execute permissions (lost in VSIX ZIP) and clears macOS quarantine (`xattr -cr`)
- Code signing (Apple Developer ID) not yet implemented — may cause "unidentified developer" warnings on macOS
