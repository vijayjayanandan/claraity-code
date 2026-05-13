---
name: review-changes
description: Review all uncommitted changes for bugs, security issues, and code quality before committing. Use when the user wants a pre-commit review or asks to review their changes.
disable-model-invocation: true
allowed-tools: Bash(git diff *) Bash(git log *) Bash(git status *) Read Grep
argument-hint: [scope]
arguments: [scope]
---

# Pre-Commit Code Review

## Changed Files
!`git diff --name-status`

## Full Diff (staged + unstaged)
!`git diff HEAD`

## Recent Commit Context
!`git log --oneline -3`

## Instructions

You are performing a thorough pre-commit code review. Analyze every change in the diff above.

### Review Checklist

For each changed file, evaluate:

1. **Correctness** - Logic errors, off-by-one, null/undefined handling, race conditions
2. **Security** - Injection risks, hardcoded secrets, exposed credentials, unsafe deserialization
3. **Performance** - N+1 queries, unnecessary loops, missing indexes, memory leaks
4. **Style** - Naming consistency, dead code, leftover debug statements (print, console.log, TODO)
5. **Tests** - Are new code paths covered? Any tests broken by these changes?

### Output Format

For each issue found, report:
- **File:Line** - exact location
- **Severity** - CRITICAL / WARNING / SUGGESTION
- **Issue** - what's wrong
- **Fix** - how to fix it

### Scope

If a scope was specified ("$scope"), only review files matching that scope (e.g., "backend" = src/, "frontend" = claraity-vscode/, "tests" = tests/).

### Summary

End with a one-line verdict:
- SHIP IT - no issues found
- FIX FIRST - critical/warning issues need attention
- NEEDS DISCUSSION - architectural concerns to talk through

If you find zero issues, say so honestly. Do not invent problems.
