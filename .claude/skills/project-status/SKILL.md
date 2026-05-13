---
name: project-status
description: Show ClarAIty project status including git state, recent activity, and open tasks. Use when the user asks about project status, what's changed recently, or what needs attention.
argument-hint: [focus-area]
arguments: [focus]
---

# Project Status Report

## Git Status
!`git status --short`

## Recent Commits (last 5)
!`git log --oneline -5`

## Branch Info
!`git branch --show-current`

## Modified Files (unstaged)
!`git diff --stat`

## Open Beads (Tasks)
!`python -m src.claraity.claraity_beads ready 2>/dev/null || echo "No beads DB available"`

## Instructions

You are providing a project status briefing. Analyze the data above and give a concise summary covering:

1. **Current branch and state** - any uncommitted work, conflicts, etc.
2. **Recent activity** - what the last few commits were about
3. **Outstanding work** - unstaged changes and open tasks

If a focus area was specified ("$focus"), zoom in on that aspect. Otherwise give the full overview.

Keep the summary brief and actionable. Flag anything that looks like it needs attention (e.g., many uncommitted changes, stale branches, blocked tasks).
