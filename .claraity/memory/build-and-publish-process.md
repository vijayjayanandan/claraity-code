---
name: Build and Publish Process
description: Full build pipeline - Python binary, VS Code extension, webview, marketplace, GitHub push
type: reference
---

## Python Binary Compilation

MUST use the dedicated build venv (not global Python which has 561+ packages including torch/langchain that slow PyInstaller to a crawl):

```bash
cd C:/Vijay/Learning/AI/ai-coding-agent
.venv-build/Scripts/python.exe -m PyInstaller claraity-server.spec --noconfirm
```

- Spec file: `claraity-server.spec`
- Output: `dist/claraity-server/` (exe + _internal/)
- Copy to extension: `cp -r dist/claraity-server/* claraity-vscode/bin/`
- Build time: ~60s with `.venv-build`, 10+ minutes with global env

**Why:** The comment in the spec says `.venv-build/Scripts/pyinstaller`. Global Python has torch, langchain etc. that PyInstaller tries to analyze even though they're excluded from the final binary.

## VS Code Extension Build

```bash
# 1. Build webview (React/Vite)
cd claraity-vscode/webview-ui && npm run build

# 2. Compile extension TypeScript (esbuild)
cd claraity-vscode && npm run compile

# 3. Package VSIX
cd claraity-vscode && npx vsce package --no-dependencies

# 4. Publish to marketplace
cd claraity-vscode && npx vsce publish --no-dependencies
```

- Publisher: `claraity.claraity-code` (changed from `VijayJayanandan.claraity-vscode` on 2026-04-15)
- Display name: `ClarAIty Code`
- Marketplace URL: https://marketplace.visualstudio.com/items?itemName=claraity.claraity-code
- VSIX includes: bin/ (Python binary), out/ (extension JS), webview-ui/dist/
- Size: ~31 MB

## Version Tagging

- Extension version (`package.json`) and repo tags are **separate** version lines
- Repo tags: `v0.16.0` etc. (check latest with `git tag -l --sort=-version:refname "v*" | head -1`)
- Extension version: in `claraity-vscode/package.json`
- Bump extension version before packaging
- Tag after commit: `git tag -a v0.X.0 -m "description"`

## GitHub Push

```bash
git push origin main --tags
```

Remote: `github.com-personal:vijayjayanandan/claraity-code.git`

## Full Release Sequence

1. Run tests
2. Commit changes
3. Bump extension version in `package.json`
4. Compile Python binary (using `.venv-build`)
5. Copy binary to `claraity-vscode/bin/`
6. Package and publish VSIX
7. Commit version bump
8. Tag release
9. Push to GitHub with tags
