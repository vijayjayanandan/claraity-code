# Delegate to Subagent Tool - Issue Analysis & Improvement Plan

## Executive Summary

The `delegate_to_subagent` tool is **non-functional** due to a critical parameter mismatch between the tool schema (what the LLM sees) and the tool implementation (what the code expects).

**Impact**: The tool cannot be invoked successfully by the LLM, making subagent delegation completely broken.

---

## Root Cause Analysis

### The Problem

**Tool Schema** (`src/tools/tool_schemas.py`, line 340-357):
```python
DELEGATE_TO_SUBAGENT_TOOL = ToolDefinition(
    name="delegate_to_subagent",
    description="Delegate a complex subtask to an independent subagent...",
    parameters={
        "type": "object",
        "properties": {
            "task_description": {  # ❌ WRONG PARAMETER NAME
                "type": "string",
                "description": "Clear description of the subtask to delegate"
            },
            "context": {  # ❌ NOT USED BY IMPLEMENTATION
                "type": "string",
                "description": "Additional context the subagent needs"
            }
        },
        "required": ["task_description"]  # ❌ MISSING 'subagent' PARAMETER
    }
)
```

**Tool Implementation** (`src/tools/delegation.py`, line 93):
```python
def execute(self, subagent: str, task: str, **kwargs: Any) -> ToolResult:
    """Execute subagent delegation.
    
    Args:
        subagent: Name of the subagent to use (e.g., 'code-reviewer')  # ✅ REQUIRED
        task: Clear description of the task to delegate                # ✅ REQUIRED
        **kwargs: Additional arguments
    """
```

### How Parameters Flow

1. **LLM generates tool call** based on schema:
   ```json
   {
     "name": "delegate_to_subagent",
     "arguments": {
       "task_description": "Review code for bugs",
       "context": "Focus on security"
     }
   }
   ```

2. **ToolExecutor receives call** and passes kwargs to tool:
   ```python
   # src/tools/base.py, line 221
   result = tool.execute(**kwargs)
   # Expands to: tool.execute(task_description="Review...", context="Focus...")
   ```

3. **Tool execute() method expects different parameters**:
   ```python
   # Expects: execute(subagent="code-reviewer", task="Review...")
   # Receives: execute(task_description="Review...", context="Focus...")
   # Result: TypeError - missing required positional arguments
   ```

### Error Observed

```
DelegateToSubagentTool.execute() missing 2 required positional arguments: 'subagent' and 'task'
```

This confirms the parameter name mismatch.

---

## Evidence from Tests

The unit tests (`tests/tools/test_delegation_tool.py`, line 93-108) show the **correct** usage:

```python
def test_execute_success(self, mock_subagent_manager):
    """Test successful delegation to subagent."""
    tool = DelegateToSubagentTool(mock_subagent_manager)
    
    # ✅ CORRECT PARAMETERS
    result = tool.execute(subagent='test-agent', task='Test task')
    
    # Verify delegation was called
    mock_subagent_manager.delegate.assert_called_once_with(
        subagent_name='test-agent',
        task_description='Test task'
    )
```

The tests pass because they call `execute()` directly with correct parameters, **bypassing the schema entirely**.

---

## Fix Plan

### Immediate Fix (Critical - P0)

**File**: `src/tools/tool_schemas.py`

**Change**: Update `DELEGATE_TO_SUBAGENT_TOOL` schema to match implementation:

```python
DELEGATE_TO_SUBAGENT_TOOL = ToolDefinition(
    name="delegate_to_subagent",
    description="Delegate a complex subtask to an independent subagent. Use for large, self-contained tasks.",
    parameters={
        "type": "object",
        "properties": {
            "subagent": {  # ✅ FIXED: Matches execute() parameter
                "type": "string",
                "description": "Name of the subagent to use (e.g., 'code-reviewer', 'test-writer')"
            },
            "task": {  # ✅ FIXED: Matches execute() parameter
                "type": "string",
                "description": "Clear description of the task to delegate"
            }
        },
        "required": ["subagent", "task"]  # ✅ FIXED: Both parameters required
    }
)
```

**Rationale**:
- Schema parameter names MUST match `execute()` method signature
- Both `subagent` and `task` are required (implementation validates both)
- Removed unused `context` parameter (not used by implementation)

---

## Areas for Improvement

### 1. Schema-Implementation Validation (P1 - High Priority)

**Problem**: No automated check ensures schemas match implementations.

**Solution**: Add schema validation test:

```python
# tests/tools/test_schema_validation.py

def test_all_tool_schemas_match_implementations():
    """Verify all tool schemas match their execute() signatures."""
    from src.tools.tool_schemas import ALL_TOOLS
    from src.tools import ToolExecutor
    import inspect
    
    executor = ToolExecutor()
    
    for tool_def in ALL_TOOLS:
        tool_name = tool_def.name
        tool = executor.tools.get(tool_name)
        
        if not tool:
            continue
            
        # Get execute() signature
        sig = inspect.signature(tool.execute)
        required_params = [
            name for name, param in sig.parameters.items()
            if param.default == inspect.Parameter.empty
            and name != 'self'
            and name != 'kwargs'
        ]
        
        # Get schema required parameters
        schema_required = tool_def.parameters.get('required', [])
        schema_properties = tool_def.parameters.get('properties', {}).keys()
        
        # Validate match
        assert set(required_params) == set(schema_required), \
            f"{tool_name}: Required params mismatch. " \
            f"Schema: {schema_required}, Implementation: {required_params}"
        
        assert all(p in schema_properties for p in required_params), \
            f"{tool_name}: Missing schema properties for required params"
```

**Benefits**:
- Catches schema-implementation mismatches at test time
- Prevents regression
- Documents expected contract

### 2. Dynamic Schema Generation (P2 - Medium Priority)

**Problem**: Schemas are manually maintained separately from implementations.

**Solution**: Generate schemas from implementation signatures:

```python
# src/tools/base.py

from typing import get_type_hints
import inspect

class Tool(ABC):
    """Base tool interface."""
    
    def __init__(self, name: str, description: str):
        self.name = name
        self.description = description
        self._schema = self._generate_schema()  # Auto-generate
    
    def _generate_schema(self) -> Dict[str, Any]:
        """Generate OpenAI-compatible schema from execute() signature."""
        sig = inspect.signature(self.execute)
        hints = get_type_hints(self.execute)
        
        properties = {}
        required = []
        
        for param_name, param in sig.parameters.items():
            if param_name in ('self', 'kwargs'):
                continue
                
            # Extract type and description from docstring
            param_type = hints.get(param_name, str)
            param_desc = self._extract_param_description(param_name)
            
            properties[param_name] = {
                "type": self._python_type_to_json_type(param_type),
                "description": param_desc
            }
            
            if param.default == inspect.Parameter.empty:
                required.append(param_name)
        
        return {
            "type": "object",
            "properties": properties,
            "required": required
        }
    
    @abstractmethod
    def execute(self, **kwargs: Any) -> ToolResult:
        """Execute the tool. Subclasses must implement."""
        pass
```

**Benefits**:
- Single source of truth (implementation)
- Impossible to have schema-implementation mismatch
- Less maintenance burden

**Trade-offs**:
- Requires well-documented execute() methods
- May need manual overrides for complex cases

### 3. Better Error Messages (P2 - Medium Priority)

**Problem**: Current error is cryptic:
```
DelegateToSubagentTool.execute() missing 2 required positional arguments: 'subagent' and 'task'
```

**Solution**: Add parameter validation in ToolExecutor:

```python
# src/tools/base.py

def execute_tool(self, tool_name: str, **kwargs: Any) -> ToolResult:
    """Execute a tool by name with parameter validation."""
    
    # ... existing code ...
    
    tool = self.tools[tool_name]
    
    # VALIDATE PARAMETERS
    sig = inspect.signature(tool.execute)
    required_params = [
        name for name, param in sig.parameters.items()
        if param.default == inspect.Parameter.empty
        and name not in ('self', 'kwargs')
    ]
    
    missing_params = [p for p in required_params if p not in kwargs]
    
    if missing_params:
        return ToolResult(
            tool_name=tool_name,
            status=ToolStatus.ERROR,
            output=None,
            error=f"Missing required parameters: {', '.join(missing_params)}. "
                  f"Provided: {', '.join(kwargs.keys())}"
        )
    
    # ... execute tool ...
```

**Benefits**:
- Clear error messages for debugging
- Helps identify schema issues quickly
- Better developer experience

### 4. Integration Test Coverage (P1 - High Priority)

**Problem**: Unit tests bypass the schema by calling `execute()` directly.

**Solution**: Add end-to-end integration tests:

```python
# tests/tools/test_delegation_integration.py

def test_delegate_via_tool_executor(mock_subagent_manager):
    """Test delegation through ToolExecutor (uses schema)."""
    from src.tools import ToolExecutor
    from src.tools.delegation import DelegateToSubagentTool
    
    executor = ToolExecutor()
    tool = DelegateToSubagentTool(mock_subagent_manager)
    executor.register_tool(tool)
    
    # Mock successful result
    mock_result = SubAgentResult(
        success=True,
        subagent_name='test-agent',
        output='Success',
        execution_time=1.0,
        tool_calls=[]
    )
    mock_subagent_manager.delegate.return_value = mock_result
    
    # Execute via ToolExecutor (uses schema)
    result = executor.execute_tool(
        'delegate_to_subagent',
        subagent='test-agent',
        task='Test task'
    )
    
    assert result.status == ToolStatus.SUCCESS
    assert result.output == 'Success'
```

**Benefits**:
- Tests actual LLM invocation path
- Catches schema issues before production
- Validates end-to-end flow

### 5. Documentation Improvements (P3 - Low Priority)

**Problem**: No clear documentation on schema-implementation contract.

**Solution**: Add developer guide:

```markdown
# docs/TOOL_DEVELOPMENT.md

## Creating a New Tool

### 1. Implement the Tool Class

```python
class MyTool(Tool):
    def execute(self, param1: str, param2: int, optional: str = "default") -> ToolResult:
        """Execute the tool.
        
        Args:
            param1: Description of param1
            param2: Description of param2
            optional: Description of optional param
        """
        # Implementation
```

### 2. Create the Schema

**CRITICAL**: Schema parameter names MUST match execute() signature exactly.

```python
MY_TOOL = ToolDefinition(
    name="my_tool",
    description="...",
    parameters={
        "type": "object",
        "properties": {
            "param1": {"type": "string", "description": "..."},  # ✅ Matches execute()
            "param2": {"type": "integer", "description": "..."},  # ✅ Matches execute()
            "optional": {"type": "string", "description": "..."}  # ✅ Matches execute()
        },
        "required": ["param1", "param2"]  # ✅ Matches required params
    }
)
```

### 3. Add Validation Test

Always add a test that validates schema matches implementation.
```

---

## Testing Strategy

### Pre-Fix Validation

1. **Reproduce the issue**:
   ```python
   from src.tools import ToolExecutor
   executor = ToolExecutor()
   result = executor.execute_tool(
       'delegate_to_subagent',
       task_description='Test',  # Wrong param name
       context='Context'
   )
   # Should fail with parameter mismatch error
   ```

2. **Verify current behavior**:
   - Tool cannot be invoked via ToolExecutor
   - Direct execute() calls work (unit tests pass)

### Post-Fix Validation

1. **Test with correct parameters**:
   ```python
   result = executor.execute_tool(
       'delegate_to_subagent',
       subagent='code-reviewer',  # Correct param name
       task='Review code'          # Correct param name
   )
   # Should succeed
   ```

2. **Run all tests**:
   ```bash
   pytest tests/tools/test_delegation_tool.py -v
   pytest tests/core/test_agent_subagent_integration.py -v
   ```

3. **Manual LLM test**:
   - Start agent with subagents enabled
   - Ask LLM to delegate a task
   - Verify delegation succeeds

---

## Implementation Checklist

### Phase 1: Critical Fix (Immediate)
- [ ] Update `DELEGATE_TO_SUBAGENT_TOOL` schema in `tool_schemas.py`
- [ ] Add integration test for delegation via ToolExecutor
- [ ] Verify fix with manual LLM test
- [ ] Update any documentation referencing old parameter names

### Phase 2: Prevention (Week 1)
- [ ] Add schema validation test for all tools
- [ ] Run validation test in CI pipeline
- [ ] Document schema-implementation contract

### Phase 3: Improvements (Week 2-3)
- [ ] Implement dynamic schema generation (optional)
- [ ] Add parameter validation in ToolExecutor
- [ ] Improve error messages
- [ ] Create tool development guide

---

## Risk Assessment

### Fix Risk: **LOW**
- Simple parameter rename in schema
- No breaking changes to implementation
- Tests validate correct behavior
- Rollback is trivial (revert commit)

### Regression Risk: **VERY LOW**
- Tool is currently broken, so fix can't make it worse
- Unit tests already validate implementation
- Integration test will catch future regressions

---

## Additional Observations

### 1. Inconsistent Parameter Naming

The implementation uses different parameter names internally:

```python
# Tool execute() method
def execute(self, subagent: str, task: str, **kwargs):
    result = self.subagent_manager.delegate(
        subagent_name=subagent,      # Maps to 'subagent_name'
        task_description=task.strip() # Maps to 'task_description'
    )
```

**Recommendation**: Consider standardizing parameter names across the stack:
- Option A: Use `subagent` and `task` everywhere (simpler, clearer)
- Option B: Use `subagent_name` and `task_description` everywhere (more explicit)

### 2. Unused Context Parameter

The schema includes a `context` parameter that the implementation ignores:

```python
# Schema has 'context', but execute() doesn't use it
def execute(self, subagent: str, task: str, **kwargs: Any):
    # 'context' would be in kwargs but is never accessed
```

**Recommendation**: Either:
- Remove `context` from schema (current fix does this)
- Implement context support in the tool (future enhancement)

### 3. Dynamic Description Generation

The tool generates a dynamic description listing available subagents:

```python
def _generate_description(self) -> str:
    """Generate dynamic tool description listing available subagents."""
    available = self.subagent_manager.get_available_subagents()
    # ... builds description with subagent list ...
```

This is **excellent design** - the LLM always sees current subagents. However, this description is separate from the schema description.

**Recommendation**: Ensure schema description stays in sync or references the dynamic description.

---

## Conclusion

The `delegate_to_subagent` tool has a **critical but easily fixable bug**: parameter name mismatch between schema and implementation.

**Immediate Action Required**:
1. Fix schema parameter names (5 minutes)
2. Add integration test (15 minutes)
3. Verify with manual test (5 minutes)

**Long-term Improvements**:
1. Add schema validation tests (prevents recurrence)
2. Consider dynamic schema generation (eliminates manual sync)
3. Improve error messages (better debugging)
4. Document tool development contract (prevents future issues)

**Estimated Total Effort**:
- Critical fix: 30 minutes
- Prevention measures: 2-4 hours
- Full improvements: 1-2 days

**Priority**: **P0 - Critical** (tool is completely non-functional)
