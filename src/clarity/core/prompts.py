"""
LLM Prompts for ClarAIty Architecture Generation

System prompts and templates for generating architecture blueprints.
"""

ARCHITECTURE_GENERATION_SYSTEM_PROMPT = """You are an expert software architect generating detailed architecture blueprints for code generation tasks.

Your role is to analyze a task description and produce a comprehensive architecture plan BEFORE any code is written.

Key responsibilities:
1. Identify all components needed (classes, functions, modules, APIs, etc.)
2. Make design decisions with clear rationale
3. Plan file actions (create/modify/delete)
4. Map relationships between components
5. Assess complexity, time estimates, and risks
6. Consider prerequisites and dependencies

Output must be structured JSON that can be parsed into a Blueprint object.

Focus on:
- **Clarity**: Explain WHY decisions are made, not just WHAT
- **Completeness**: Cover all aspects of the implementation
- **Practicality**: Be realistic about complexity and time
- **Safety**: Identify risks and prerequisites upfront

Remember: This blueprint will be shown to the user for approval BEFORE code generation begins.
"""


def generate_architecture_prompt(
    task_description: str,
    codebase_context: str = "",
    existing_patterns: str = "",
) -> str:
    """
    Generate the prompt for architecture blueprint creation.

    Args:
        task_description: The user's task/feature request
        codebase_context: Context about existing codebase structure
        existing_patterns: Existing patterns/conventions to follow

    Returns:
        Complete prompt for LLM
    """
    prompt = f"""# Task
{task_description}

# Codebase Context
{codebase_context if codebase_context else "No existing codebase context provided."}

# Existing Patterns
{existing_patterns if existing_patterns else "No specific patterns to follow."}

# Your Task
Generate a complete architecture blueprint for implementing this task. Provide your response as a JSON object with the following structure:

```json
{{
  "task_description": "Restate the task clearly",
  "components": [
    {{
      "name": "ComponentName",
      "type": "class|function|module|api|database|ui|service",
      "purpose": "High-level purpose of this component",
      "responsibilities": ["Responsibility 1", "Responsibility 2"],
      "file_path": "relative/path/to/file.py",
      "layer": "core|workflow|memory|tools|rag|ui",
      "key_methods": ["method1", "method2"],
      "dependencies": ["ComponentA", "ComponentB"]
    }}
  ],
  "design_decisions": [
    {{
      "decision": "Clear statement of the decision",
      "rationale": "WHY this decision was made",
      "alternatives_considered": ["Alternative 1", "Alternative 2"],
      "trade_offs": "What we gain vs what we lose",
      "category": "architecture|technology|pattern"
    }}
  ],
  "file_actions": [
    {{
      "file_path": "relative/path/to/file.py",
      "action": "create|modify|delete",
      "description": "What changes will be made",
      "estimated_lines": 100,
      "components_affected": ["ComponentA"]
    }}
  ],
  "relationships": [
    {{
      "source": "ComponentA",
      "target": "ComponentB",
      "type": "calls|imports|inherits|uses|depends_on",
      "description": "How they interact"
    }}
  ],
  "estimated_complexity": "low|medium|high",
  "estimated_time": "5 minutes|30 minutes|2 hours|etc",
  "prerequisites": ["Prerequisite 1", "Prerequisite 2"],
  "risks": ["Risk 1", "Risk 2"]
}}
```

# Guidelines
1. **Components**: Identify ALL components needed. Be specific about types and responsibilities.
2. **Design Decisions**: Explain WHY choices are made. Consider alternatives. Be honest about trade-offs.
3. **File Actions**: List every file that will be created/modified. Estimate lines of code.
4. **Relationships**: Map how components interact. This helps visualize the architecture.
5. **Complexity/Time**: Be realistic. Don't underestimate.
6. **Prerequisites**: What needs to exist first? (libraries, APIs, data, etc.)
7. **Risks**: What could go wrong? (breaking changes, performance, complexity, etc.)

# Important
- Think like an architect, not a coder. Focus on the BIG PICTURE.
- User will review this BEFORE code is generated. Make it clear and informative.
- If something is unclear, state assumptions explicitly in design decisions.

Generate the blueprint now:"""

    return prompt


def generate_refinement_prompt(
    blueprint_json: str,
    user_feedback: str,
) -> str:
    """
    Generate prompt for refining a blueprint based on user feedback.

    Args:
        blueprint_json: Current blueprint as JSON string
        user_feedback: User's comments/requests for changes

    Returns:
        Prompt for LLM to refine the blueprint
    """
    return f"""# Current Blueprint
```json
{blueprint_json}
```

# User Feedback
{user_feedback}

# Your Task
Refine the architecture blueprint based on the user's feedback. Keep the same JSON structure, but update components, design decisions, or other elements as requested.

Make sure to:
1. Address the user's specific concerns
2. Update design decisions to reflect why changes were made
3. Update relationships if components changed
4. Recalculate complexity/time if scope changed

Provide the COMPLETE refined blueprint as JSON:"""


# Example codebase context templates
CODEBASE_CONTEXT_TEMPLATE = """
Project: {project_name}
Structure:
{directory_structure}

Key existing components:
{existing_components}

Patterns/Conventions:
{patterns}
"""


# Example for extracting context from existing codebase
def build_codebase_context(
    project_name: str = "AI Coding Agent",
    key_dirs: list = None,
    key_files: list = None,
    patterns: list = None,
) -> str:
    """
    Build codebase context string for architecture generation.

    Args:
        project_name: Name of the project
        key_dirs: List of key directories
        key_files: List of key files with descriptions
        patterns: List of patterns/conventions

    Returns:
        Formatted codebase context string
    """
    context_parts = [f"Project: {project_name}", ""]

    if key_dirs:
        context_parts.append("Key Directories:")
        for dir_path in key_dirs:
            context_parts.append(f"  - {dir_path}")
        context_parts.append("")

    if key_files:
        context_parts.append("Key Files:")
        for file_desc in key_files:
            context_parts.append(f"  - {file_desc}")
        context_parts.append("")

    if patterns:
        context_parts.append("Patterns/Conventions:")
        for pattern in patterns:
            context_parts.append(f"  - {pattern}")
        context_parts.append("")

    return "\n".join(context_parts)
