---
name: Build and Publish Process
description: Full build pipeline - CI multi-platform builds, local dev builds, unified versioning, marketplace publish
type: reference
---

## Versioning (unified as of v1.0.0)

**Single version across all sources.** Previously repo tags, `pyproject.toml`, and `package.json` had independent version lines that drifted apart. Unified to `1.0.0` on 2026-04-25.

| Source | Purpose |
|--------|---------|
| `claraity-vscode/package.json` `"version"` | Extension version (marketplace) |
| `pyproject.toml` `version` | Python package version |
| `python-env.ts` `MIN_AGENT_VERSION` | Minimum compatible server version |
| Git tag (`v1.0.0`) | Release trigger |

**All four must match on release.** Bump all before tagging.

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
- **Manual (`workflow_dispatch`):** Builds all 4 platforms, publish optional (checkbox)

**Requires:** `VSCE_PAT` secret in GitHub repo settings for marketplace publish.

Platform-targeted VSIXes (`vsce package --target`) let the marketplace serve the right binary per OS automatically. Each VSIX is ~31 MB (single platform).

### macOS-specific handling in `python-env.ts`
- `chmod 755` — restores execute permission lost during VSIX ZIP packaging
- `xattr -cr` — clears macOS Gatekeeper quarantine attribute on downloaded binaries

## Local Dev Build (Windows only, for testing)

MUST use the dedicated build venv (not global Python which has 561+ packages):

```bash
cd C:/Vijay/Learning/AI/ai-coding-agent
.venv-build/Scripts/python.exe -m PyInstaller claraity-server.spec --noconfirm
cp -r dist/claraity-server/* claraity-vscode/bin/
```

- Build time: ~60s with `.venv-build`, 10+ minutes with global env
- Produces Windows binary only — cannot cross-compile for macOS/Linux

## VS Code Extension Build (local, single-platform)

```bash
cd claraity-vscode/webview-ui && npm run build    # Webview (React/Vite)
cd claraity-vscode && npm run compile              # Extension (esbuild)
cd claraity-vscode && npx vsce package --no-dependencies  # VSIX (no --target for local)
```

- Publisher: `claraity.claraity-code`
- Marketplace URL: https://marketplace.visualstudio.com/items?itemName=claraity.claraity-code
- VSIX includes: bin/ (Python binary), out/ (extension JS), webview-ui/dist/

## GitHub Push

```bash
git push origin main --tags
```

Remote: `github.com-personal:vijayjayanandan/claraity-code.git`

## Full Release Sequence

1. Run tests
2. Commit all changes
3. Bump version in `package.json`, `pyproject.toml`, and `MIN_AGENT_VERSION` in `python-env.ts`
4. Commit version bump
5. Tag: `git tag -a v1.X.0 -m "description"`
6. Push: `git push origin main --tags`
7. CI auto-triggers:
   - Builds binaries on 4 platforms (Windows, macOS Intel, macOS ARM, Linux)
   - Packages 4 platform-targeted VSIXes
   - Publishes all to marketplace
