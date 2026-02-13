# Jira & Confluence Integration Guide

**Quick Reference for AI Agents**

---

## Project Information

**Confluence Space**: ClarAIty Code (CC)
- Space ID: `557060`
- URL: `https://vijayjayanandan.atlassian.net/wiki/spaces/CC`
- Purpose: Architecture docs, implementation guides, technical documentation

**Jira Project**: ClarAIty Code (CC)
- Project Key: `CC`
- Project ID: `10033`
- URL: `https://vijayjayanandan.atlassian.net/browse/CC`
- Purpose: User stories, dev tasks, testing tasks, bug tracking

**Cloud ID** (always use): `fcd96f11-1610-4860-b036-6fb42ce58d98`

---

## Creating User Stories with Subtasks

### Pattern: Feature Implementation Story

```python
# 1. Create user story
story = jira_createJiraIssue(
    cloudId="fcd96f11-1610-4860-b036-6fb42ce58d98",
    projectKey="CC",
    issueTypeName="Story",
    summary="Implement [Feature Name]",
    description="""## User Story

As a developer, I want [feature] so that [benefit].

## Implementation Summary

**Status**: ✅ COMPLETED

Implemented a production-grade [feature] with:
- **Key capability 1**
- **Key capability 2**
- **Key capability 3**

### Key Components Implemented

1. **Component1** (`file1.py`) - Purpose
2. **Component2** (`file2.py`) - Purpose

### Architecture

[ASCII diagram or description]

### Performance Characteristics

- Metric 1: Value
- Metric 2: Value

## Acceptance Criteria

* ✅ Criterion 1
* ✅ Criterion 2
* ✅ Criterion 3

## Documentation

See Confluence: [Title](https://vijayjayanandan.atlassian.net/wiki/spaces/CC/pages/XXXXX)
"""
)

# 2. Create DEV subtask
dev_task = jira_createJiraIssue(
    cloudId="fcd96f11-1610-4860-b036-6fb42ce58d98",
    projectKey="CC",
    issueTypeName="Sub-task",
    summary="DEV: Implement [feature] infrastructure",
    description="""## Development Task

Implement the [feature] with [key aspects].

### Changes Implemented

**Files Created:**

- `src/path/file1.py` - Component1
  - Implemented X, Y, Z
  - Key methods: `method1()`, `method2()`
  - Exports: `function1()`, `function2()`

- `src/path/file2.py` - Component2
  - Implemented A, B, C
  - Database schema: [schema details]
  - API: `api_method()`

**Files Modified:**

- `src/core/agent.py` - Integration points
  - Added `_feature_method()` at line X
  - Modified `existing_method()` to support feature

### Technical Details

**Architecture:**
- Design pattern used
- Key decisions and rationale

**Performance:**
- Benchmarks
- Optimization notes

### Status
✅ Completed - All components implemented and integrated
""",
    parent=story["key"]  # e.g., "CC-4"
)

# 3. Create TEST subtask
test_task = jira_createJiraIssue(
    cloudId="fcd96f11-1610-4860-b036-6fb42ce58d98",
    projectKey="CC",
    issueTypeName="Sub-task",
    summary="TEST: Validate [feature] functionality",
    description="""## Testing Task

Comprehensive testing of the [feature] components.

### Test Scripts Created

**Test Files:**
- `tests/path/test_component1.py` - Component1 tests (X tests)
- `tests/path/test_component2.py` - Component2 tests (Y tests)

### Test Coverage

**1. Unit Tests**
```python
def test_feature_basic():
    # Test basic functionality
    result = feature_function()
    assert result.success == True

def test_feature_edge_cases():
    # Test edge cases
    ...
```

**2. Integration Tests**
```python
def test_feature_integration():
    # Test integration with other components
    ...
```

### Test Execution

```bash
# Run all tests
pytest tests/path/ -v

# Run with coverage
pytest tests/path/ --cov=src.path --cov-report=html
```

### Test Results

✅ **All tests passing**
- X test cases executed
- Coverage: Y%
- No regressions detected

### Manual Testing Checklist

- [x] Feature works in normal conditions
- [x] Edge cases handled correctly
- [x] Error handling works
- [x] Performance meets targets

### Status
✅ Completed - All tests passing, coverage targets met
""",
    parent=story["key"]
)
```

### Transitioning Issues to Done

```python
# 1. Get available transitions
transitions = jira_getTransitionsForJiraIssue(
    cloudId="fcd96f11-1610-4860-b036-6fb42ce58d98",
    issueIdOrKey="CC-4"
)

# 2. Find "Done" transition (usually ID "41" or "31")
# Look for: transition["name"] == "Done"

# 3. Transition all issues
jira_transitionJiraIssue(
    cloudId="fcd96f11-1610-4860-b036-6fb42ce58d98",
    issueIdOrKey="CC-5",  # Dev task
    transition={"id": "41"}
)

jira_transitionJiraIssue(
    cloudId="fcd96f11-1610-4860-b036-6fb42ce58d98",
    issueIdOrKey="CC-6",  # Test task
    transition={"id": "41"}
)

jira_transitionJiraIssue(
    cloudId="fcd96f11-1610-4860-b036-6fb42ce58d98",
    issueIdOrKey="CC-4",  # Parent story
    transition={"id": "41"}
)
```

---

## Confluence Documentation

### Writing Condensed Documentation

**Guidelines:**
- Target: 300-400 lines (not 1000+)
- LLM-friendly: Clear signposts for deep dives
- Human-friendly: Quick start, patterns, troubleshooting

**Structure:**
```markdown
# Component Name

**Purpose**: One-line summary
**Status**: Production Ready
**Last Updated**: YYYY-MM-DD

---

## Quick Start (30 seconds)

[Minimal code example to get started]

---

## Architecture Overview

### Design Philosophy

[One sentence summary]

[ASCII diagram]

### Key Design Decisions

| Decision | Rationale | Trade-off |
|----------|-----------|-----------|
| Choice 1 | Why | Pro vs Con |

---

## Core Components

### 1. ComponentName
**Location**: `src/path/file.py`

**What it does**: [Brief description]

**Key APIs**:
- `method1()` - Purpose
- `method2()` - Purpose

**Deep dive**: Read this file for [specific details].

---

## Common Usage Patterns

### Pattern 1: [Name]
```python
# Example code
```

---

## Troubleshooting

| Symptom | Cause | Fix |
|---------|-------|-----|
| Error X | Reason | Solution |

---

## Deep Dive References

### For LLMs
When you need to understand or modify [component], read these files in order:
1. **`file1.py`** - Start here for [aspect]
2. **`file2.py`** - [Aspect]

### For Humans
- **Quick reference**: This document
- **API docs**: Docstrings in `src/path/__init__.py`
- **Examples**: `tests/path/` directory
```

### Creating Confluence Pages

```python
# Create new page
page = jira_createConfluencePage(
    cloudId="fcd96f11-1610-4860-b036-6fb42ce58d98",
    spaceId="557060",  # ClarAIty Code space
    title="Component Architecture",
    body="# Markdown content here...",
    contentFormat="markdown"
)
# Returns: {"id": "655362", "title": "...", ...}

# Update existing page
jira_updateConfluencePage(
    cloudId="fcd96f11-1610-4860-b036-6fb42ce58d98",
    pageId="655362",
    title="Updated Title",  # Optional
    body="# Updated content...",
    contentFormat="markdown"
)

# Get pages in space
pages = jira_getPagesInConfluenceSpace(
    cloudId="fcd96f11-1610-4860-b036-6fb42ce58d98",
    spaceId="557060"
)

# Get specific page
page = jira_getConfluencePage(
    cloudId="fcd96f11-1610-4860-b036-6fb42ce58d98",
    pageId="655362",
    contentFormat="markdown"
)
```

---

## Linking Jira to Confluence

### Method 1: In Description (via API)

Include Confluence link in Jira issue description:

```markdown
## Documentation

See Confluence: [Page Title](https://vijayjayanandan.atlassian.net/wiki/spaces/CC/pages/655362)
```

### Method 2: Remote Links (Manual in UI)

**User adds in Jira UI:**
1. Open Jira issue
2. Click "Link" button
3. Select "Web Link"
4. Paste Confluence URL
5. Click "Link"

**Result:**
- Creates bidirectional link
- Visible via API: `jira_getJiraIssueRemoteIssueLinks(issueIdOrKey="CC-4")`
- Shows as "Wiki Page" relationship in Jira
- Confluence page shows related Jira issues

**API Response:**
```json
{
  "id": 10000,
  "globalId": "appId=...&pageId=655362",
  "application": {
    "type": "com.atlassian.confluence",
    "name": "System Confluence"
  },
  "relationship": "Wiki Page",
  "object": {
    "url": "https://vijayjayanandan.atlassian.net/wiki/pages/viewpage.action?pageId=655362",
    "title": "MCP Integration Infrastructure"
  }
}
```

---

## Issue Types Reference

| Issue Type | ID | Use For | Can Have Subtasks? |
|------------|----|---------|--------------------|
| **Story** | 10007 | User stories, features | Yes |
| **Sub-task** | 10041 | Tasks under stories | No |
| **Task** | 10040 | Standalone tasks | Yes |
| **Bug** | 10042 | Bug reports | Yes |
| **Epic** | 10000 | Large initiatives | Yes |

---

## Common Workflows

### Workflow 1: Document New Feature

1. **Write condensed docs** (~300-400 lines)
   - Follow structure above
   - Include Quick Start, Architecture, Patterns, Troubleshooting
   
2. **Upload to Confluence**
   ```python
   page = jira_createConfluencePage(
       cloudId="fcd96f11-1610-4860-b036-6fb42ce58d98",
       spaceId="557060",
       title="Feature Name",
       body=doc_content,
       contentFormat="markdown"
   )
   ```

3. **Create Jira story** with implementation summary and Confluence link

4. **Create dev subtask** with file-by-file changes

5. **Create test subtask** with test scripts and results

6. **Transition all to Done**

### Workflow 2: Update Existing Documentation

1. **Read current version**
   ```python
   page = jira_getConfluencePage(pageId="655362", contentFormat="markdown")
   ```

2. **Update content**
   ```python
   jira_updateConfluencePage(
       pageId="655362",
       body=updated_content,
       contentFormat="markdown"
   )
   ```

3. **Update related Jira issue** if needed

---

## Search and Query

### Search Jira Issues

```python
# Search by JQL
issues = jira_searchJiraIssuesUsingJql(
    cloudId="fcd96f11-1610-4860-b036-6fb42ce58d98",
    jql="project = CC AND status = Done ORDER BY created DESC",
    fields=["summary", "status", "description"]
)

# Search by text
results = jira_search(query="logging infrastructure")
```

### Search Confluence

```python
# Search by CQL
results = jira_searchConfluenceUsingCql(
    cloudId="fcd96f11-1610-4860-b036-6fb42ce58d98",
    cql='space = "CC" AND type = page AND title ~ "architecture"'
)

# General search
results = jira_search(query="MCP integration")
```

---

## Best Practices

1. **Always use Cloud ID**: `fcd96f11-1610-4860-b036-6fb42ce58d98`

2. **Keep docs concise**: 300-400 lines, not 1000+

3. **Structure for LLMs**: Use "Deep dive: Read file X" pointers

4. **Link everything**: Jira ↔ Confluence ↔ Code

5. **Mark tasks complete**: Don't leave stories in "To Do" when done

6. **Use subtasks**: Break stories into DEV and TEST subtasks

7. **Document test results**: Include coverage %, test counts, manual checklist

8. **Include code examples**: In both Jira descriptions and Confluence docs

9. **Use tables**: For comparisons, references, troubleshooting

10. **ASCII diagrams**: For architecture overviews (renders in both Jira and Confluence)

---

## Troubleshooting

### Issue: Can't move issues between projects

**Solution**: Use Jira UI → Issue → "•••" → "Move" → Select target project

### Issue: Confluence page not updating

**Symptom**: `jira_updateConfluencePage` times out

**Solution**: 
- Check MCP connection: `/connect-jira` in TUI
- Retry after a few seconds
- Verify pageId is correct

### Issue: Transition not working

**Symptom**: Issue doesn't move to "Done"

**Solution**:
- Get transitions first: `jira_getTransitionsForJiraIssue()`
- Find correct transition ID (varies by project)
- Use that ID in `jira_transitionJiraIssue()`

### Issue: Subtask created in wrong project

**Symptom**: Subtask has different project key than parent

**Solution**: 
- Subtasks inherit parent's project automatically
- If parent is in SCRUM, subtask will be SCRUM-X
- Move parent first, then create subtasks

---

## Examples from This Session

### Logging Infrastructure Story

- **Story**: CC-1 (moved from SCRUM-5)
- **Dev Task**: CC-2 (SCRUM-6)
- **Test Task**: CC-3 (SCRUM-7)
- **Confluence**: [ClarAIty Logging Architecture](https://vijayjayanandan.atlassian.net/wiki/spaces/CC/pages/491523)

### MCP Integration Story

- **Story**: CC-4
- **Dev Task**: CC-5
- **Test Task**: CC-6
- **Confluence**: [MCP Integration Infrastructure](https://vijayjayanandan.atlassian.net/wiki/spaces/CC/pages/655362)

Both stories follow the pattern documented above.
