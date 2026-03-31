# Contributing Guide

## Branching Strategy

We use a simplified Git Flow:

```
main (stable) ────●─────────●─────────●────► releases (tagged)
                  │         │         │
                  │   PR    │   PR    │
                  │         │         │
develop ─────●────●────●────●────●────●────► integration
             │         │         │
             │    feature/xyz    │
             │         │         │
             └─────────┴─────────┘
```

### Branches

| Branch | Purpose | Protected |
|--------|---------|-----------|
| `main` | Stable, production-ready | Yes |
| `develop` | Integration branch | Yes |
| `feature/*` | New features | No |
| `fix/*` | Bug fixes | No |
| `release/*` | Release preparation | No |

### Workflow

1. **Start a feature:**
   ```bash
   git checkout develop
   git pull origin develop
   git checkout -b feature/my-feature
   ```

2. **Work on your feature:**
   ```bash
   # Make changes
   git add .
   git commit -m "Add my feature"
   ```

3. **Push and create PR:**
   ```bash
   git push origin feature/my-feature
   # Create PR to develop on GitHub
   ```

4. **After PR is merged to develop:**
   ```bash
   git checkout develop
   git pull origin develop
   git branch -d feature/my-feature
   ```

## Versioning

We use [Semantic Versioning](https://semver.org/):

- **MAJOR.MINOR.PATCH** (e.g., `1.2.3`)
- **MAJOR**: Breaking changes
- **MINOR**: New features (backward compatible)
- **PATCH**: Bug fixes

### Creating a Release

1. **Prepare release from develop:**
   ```bash
   git checkout main
   git pull origin main
   git merge develop
   ```

2. **Update version in pyproject.toml:**
   ```toml
   version = "0.14.2"
   ```

3. **Commit and tag:**
   ```bash
   git add pyproject.toml
   git commit -m "Bump version to 0.14.2"
   git tag -a v0.14.2 -m "Release v0.14.2: Description of changes"
   ```

4. **Push:**
   ```bash
   git push origin main
   git push origin v0.14.2
   ```

5. **GitHub Release is created automatically** via the release workflow.

### Rolling Back

To rollback to a previous version:

```bash
# List available versions
git tag -l

# Checkout a specific version
git checkout v0.1.0

# Or create a branch from a tag
git checkout -b hotfix/from-v0.1.0 v0.1.0
```

## Code Quality

### Before Submitting a PR

1. **Run linting:**
   ```bash
   ruff check src/
   ruff format src/
   ```

2. **Run tests:**
   ```bash
   pytest tests/ -v
   ```

3. **Check types (optional):**
   ```bash
   mypy src/ --ignore-missing-imports
   ```

### CI Checks

All PRs must pass:
- Ruff linting
- Tests on Python 3.10, 3.11, 3.12
- Tests on Ubuntu and Windows

## Commit Messages

Use clear, descriptive commit messages:

```
<type>: <description>

[optional body]

[optional footer]
```

Types:
- `feat`: New feature
- `fix`: Bug fix
- `docs`: Documentation
- `refactor`: Code refactoring
- `test`: Adding tests
- `chore`: Maintenance tasks

Examples:
```
feat: Add context window progress bar to status bar
fix: Resolve TUI performance issue caused by CSS hover effects
docs: Update README with installation instructions
```
