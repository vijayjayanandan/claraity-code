"""Prompt templates optimized for coding tasks."""

from enum import Enum
from typing import Any, Optional

from jinja2 import Template


class TaskType(str, Enum):
    """Types of coding tasks."""

    IMPLEMENT = "implement"
    DEBUG = "debug"
    REFACTOR = "refactor"
    EXPLAIN = "explain"
    REVIEW = "review"
    TEST = "test"
    DOCUMENT = "document"


class PromptTemplate:
    """A reusable prompt template with variable substitution."""

    def __init__(self, template: str, task_type: TaskType, examples: list[str] | None = None):
        """
        Initialize prompt template.

        Args:
            template: Jinja2 template string
            task_type: Type of task this template is for
            examples: Optional few-shot examples
        """
        self.template = Template(template)
        self.task_type = task_type
        self.examples = examples or []

    def render(self, **kwargs: Any) -> str:
        """Render template with variables."""
        return self.template.render(**kwargs)

    def add_example(self, example: str) -> None:
        """Add a few-shot example."""
        self.examples.append(example)


class PromptLibrary:
    """
    Library of optimized prompts for different coding tasks.
    Designed for small LLMs with limited context windows.
    """

    # Implementation prompts
    IMPLEMENT_FEATURE = PromptTemplate(
        template="""<task>Implement the following feature</task>

<requirement>
{{ requirement }}
</requirement>

{% if context %}
<existing_code>
{{ context }}
</existing_code>
{% endif %}

{% if constraints %}
<constraints>
{{ constraints }}
</constraints>
{% endif %}

<instructions>
1. Analyze the requirement carefully
2. Consider edge cases and error handling
3. Write clean, maintainable code
4. Include docstrings/comments
5. Follow best practices for {{ language }}
</instructions>

Provide your implementation:""",
        task_type=TaskType.IMPLEMENT,
    )

    # Debugging prompts
    DEBUG_CODE = PromptTemplate(
        template="""<task>Debug the following code issue</task>

<problem>
{{ problem_description }}
</problem>

<code>
{{ code }}
</code>

{% if error_message %}
<error>
{{ error_message }}
</error>
{% endif %}

<approach>
1. Identify the root cause
2. Explain what's wrong
3. Provide a fix
4. Suggest how to prevent similar issues
</approach>

Your analysis and fix:""",
        task_type=TaskType.DEBUG,
    )

    # Refactoring prompts
    REFACTOR_CODE = PromptTemplate(
        template="""<task>Refactor the following code</task>

<code>
{{ code }}
</code>

<goals>
{{ refactoring_goals }}
</goals>

{% if principles %}
<principles>
{{ principles }}
</principles>
{% endif %}

<approach>
1. Identify code smells and issues
2. Apply appropriate refactoring patterns
3. Preserve functionality
4. Improve readability and maintainability
</approach>

Provide refactored code with explanation:""",
        task_type=TaskType.REFACTOR,
    )

    # Explanation prompts
    EXPLAIN_CODE = PromptTemplate(
        template="""<task>Explain the following code</task>

<code>
{{ code }}
</code>

{% if focus_areas %}
<focus>
{{ focus_areas }}
</focus>
{% endif %}

<format>
1. High-level purpose
2. Step-by-step logic
3. Key concepts/patterns
4. Potential improvements
</format>

Your explanation:""",
        task_type=TaskType.EXPLAIN,
    )

    # Code review prompts
    REVIEW_CODE = PromptTemplate(
        template="""<task>Review the following code</task>

<code>
{{ code }}
</code>

<review_aspects>
- Correctness and logic
- Code quality and style
- Performance considerations
- Security issues
- Best practices
{% if additional_aspects %}
- {{ additional_aspects }}
{% endif %}
</review_aspects>

Provide structured review:
1. **Strengths**: What's done well
2. **Issues**: Problems found (prioritized)
3. **Suggestions**: Specific improvements
4. **Rating**: Overall quality (1-5)

Your review:""",
        task_type=TaskType.REVIEW,
    )

    # Test generation prompts
    GENERATE_TESTS = PromptTemplate(
        template="""<task>Generate tests for the following code</task>

<code>
{{ code }}
</code>

<test_framework>
{{ framework }}
</test_framework>

<coverage_requirements>
- Happy path scenarios
- Edge cases
- Error conditions
- Boundary values
{% if custom_requirements %}
- {{ custom_requirements }}
{% endif %}
</coverage_requirements>

Generate comprehensive tests:""",
        task_type=TaskType.TEST,
    )

    # Documentation prompts
    GENERATE_DOCS = PromptTemplate(
        template="""<task>Generate documentation for the following code</task>

<code>
{{ code }}
</code>

<doc_style>
{{ style }}
</doc_style>

<include>
- Purpose and functionality
- Parameters and returns
- Usage examples
- Edge cases and limitations
{% if additional_sections %}
- {{ additional_sections }}
{% endif %}
</include>

Generate documentation:""",
        task_type=TaskType.DOCUMENT,
    )

    @classmethod
    def get_template(cls, task_type: TaskType) -> PromptTemplate:
        """Get template for task type."""
        templates = {
            TaskType.IMPLEMENT: cls.IMPLEMENT_FEATURE,
            TaskType.DEBUG: cls.DEBUG_CODE,
            TaskType.REFACTOR: cls.REFACTOR_CODE,
            TaskType.EXPLAIN: cls.EXPLAIN_CODE,
            TaskType.REVIEW: cls.REVIEW_CODE,
            TaskType.TEST: cls.GENERATE_TESTS,
            TaskType.DOCUMENT: cls.GENERATE_DOCS,
        }
        return templates.get(task_type, cls.IMPLEMENT_FEATURE)

    @classmethod
    def create_custom_template(cls, template_str: str, task_type: TaskType) -> PromptTemplate:
        """Create a custom template."""
        return PromptTemplate(template=template_str, task_type=task_type)
