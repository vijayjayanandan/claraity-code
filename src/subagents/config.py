"""SubAgent configuration parser for Markdown + YAML format.

Subagent configurations are stored as Markdown files with YAML frontmatter:
- Frontmatter: name, description, tools, model, context_window
- Body: Specialized system prompt for the subagent

Configuration files are loaded hierarchically:
1. Project: .claude/agents/*.md (highest priority)
2. User: ~/.claude/agents/*.md (lower priority)
"""

from dataclasses import dataclass, field
from pathlib import Path
from typing import List, Optional, Dict, Any
import re
import yaml
import logging

logger = logging.getLogger(__name__)


@dataclass
class SubAgentConfig:
    """Configuration for a subagent.

    Attributes:
        name: Unique lowercase identifier (e.g., "code-reviewer")
        description: Natural language description for automatic delegation
        system_prompt: Specialized system prompt (from Markdown body)
        tools: List of allowed tools (None = inherit all)
        model: Model to use (None = inherit from main agent)
        context_window: Context window size (None = inherit from main agent)
        config_path: Path to the configuration file
        metadata: Additional metadata from YAML frontmatter
    """

    name: str
    description: str
    system_prompt: str
    tools: Optional[List[str]] = None
    model: Optional[str] = None
    context_window: Optional[int] = None
    config_path: Optional[Path] = None
    metadata: Dict[str, Any] = field(default_factory=dict)

    def __post_init__(self):
        """Validate configuration after initialization."""
        # Validate name (lowercase, alphanumeric + hyphens)
        if not re.match(r'^[a-z0-9]+(?:-[a-z0-9]+)*$', self.name):
            raise ValueError(
                f"Invalid subagent name '{self.name}': "
                "must be lowercase alphanumeric with hyphens (e.g., 'code-reviewer')"
            )

        # Validate description is not empty
        if not self.description or not self.description.strip():
            raise ValueError(f"Subagent '{self.name}' must have a description")

        # Validate system prompt is not empty
        if not self.system_prompt or not self.system_prompt.strip():
            raise ValueError(f"Subagent '{self.name}' must have a system prompt")

        # Normalize tools list
        if self.tools:
            # Remove empty strings and normalize
            self.tools = [t.strip() for t in self.tools if t and t.strip()]

    @classmethod
    def from_file(cls, file_path: Path) -> 'SubAgentConfig':
        """Load subagent configuration from Markdown file.

        Args:
            file_path: Path to .md file with YAML frontmatter

        Returns:
            SubAgentConfig instance

        Raises:
            FileNotFoundError: If file doesn't exist
            ValueError: If file format is invalid

        Example:
            >>> config = SubAgentConfig.from_file(Path(".claude/agents/code-reviewer.md"))
            >>> print(config.name)
            'code-reviewer'
        """
        if not file_path.exists():
            raise FileNotFoundError(f"Configuration file not found: {file_path}")

        logger.debug(f"Loading subagent config from {file_path}")

        # Read file
        content = file_path.read_text(encoding='utf-8')

        # Parse YAML frontmatter and Markdown body
        frontmatter, body = cls._parse_markdown_with_frontmatter(content)

        # Extract required fields
        try:
            name = frontmatter['name']
            description = frontmatter['description']
        except KeyError as e:
            raise ValueError(
                f"Configuration file {file_path} missing required field: {e}"
            )

        # Extract optional fields
        tools = frontmatter.get('tools')
        if tools:
            # Tools can be comma-separated string or list
            if isinstance(tools, str):
                tools = [t.strip() for t in tools.split(',') if t.strip()]
            elif not isinstance(tools, list):
                raise ValueError(
                    f"'tools' field must be a comma-separated string or list, got {type(tools)}"
                )

        model = frontmatter.get('model')
        if model == 'inherit':
            model = None  # None means inherit from main agent

        context_window = frontmatter.get('context_window')
        if context_window is not None:
            try:
                context_window = int(context_window)
            except (ValueError, TypeError):
                raise ValueError(
                    f"'context_window' must be an integer, got {context_window}"
                )

        # Remove standard fields from metadata
        metadata = {
            k: v for k, v in frontmatter.items()
            if k not in {'name', 'description', 'tools', 'model', 'context_window'}
        }

        # Create config
        return cls(
            name=name,
            description=description,
            system_prompt=body.strip(),
            tools=tools,
            model=model,
            context_window=context_window,
            config_path=file_path,
            metadata=metadata
        )

    @staticmethod
    def _parse_markdown_with_frontmatter(content: str) -> tuple[Dict[str, Any], str]:
        """Parse Markdown file with YAML frontmatter.

        Format:
            ---
            key: value
            ---

            Markdown body here

        Args:
            content: File content

        Returns:
            Tuple of (frontmatter_dict, markdown_body)

        Raises:
            ValueError: If frontmatter format is invalid
        """
        # Match YAML frontmatter (between --- delimiters)
        pattern = r'^---\s*\n(.*?)\n---\s*\n(.*)$'
        match = re.match(pattern, content, re.DOTALL)

        if not match:
            raise ValueError(
                "Invalid format: Expected YAML frontmatter between --- delimiters"
            )

        frontmatter_yaml = match.group(1)
        markdown_body = match.group(2)

        # Parse YAML
        try:
            frontmatter = yaml.safe_load(frontmatter_yaml)
            if frontmatter is None:
                frontmatter = {}
        except yaml.YAMLError as e:
            raise ValueError(f"Invalid YAML frontmatter: {e}")

        if not isinstance(frontmatter, dict):
            raise ValueError(
                f"Frontmatter must be a YAML object (dict), got {type(frontmatter)}"
            )

        return frontmatter, markdown_body

    @classmethod
    def create_template(cls, name: str, description: str, output_path: Path) -> Path:
        """Create a template subagent configuration file.

        Args:
            name: Subagent name (lowercase, hyphens allowed)
            description: Brief description
            output_path: Path to save the template

        Returns:
            Path to created file

        Example:
            >>> SubAgentConfig.create_template(
            ...     "my-agent",
            ...     "My custom subagent",
            ...     Path(".claude/agents/my-agent.md")
            ... )
        """
        # Validate name format
        if not re.match(r'^[a-z0-9]+(?:-[a-z0-9]+)*$', name):
            raise ValueError(
                f"Invalid name '{name}': must be lowercase alphanumeric with hyphens"
            )

        template = f"""---
name: {name}
description: {description}
tools: Read, Write, Edit  # Comma-separated list of allowed tools (optional)
model: inherit  # Model to use: 'inherit', 'opus', 'sonnet', 'haiku', or specific model name
context_window: null  # Context window size (null = inherit from main agent)
---

# {name.replace('-', ' ').title()} Subagent

You are an expert in [YOUR DOMAIN].

## Your Responsibilities:
- [Responsibility 1]
- [Responsibility 2]
- [Responsibility 3]

## Expertise Areas:
- [Area 1]
- [Area 2]
- [Area 3]

## Approach:
- [How you approach tasks]
- [Your methodology]

## Output Format:
[Describe the format of your outputs]

## Examples:
[Provide examples of good outputs]
"""

        # Create parent directories if needed
        output_path.parent.mkdir(parents=True, exist_ok=True)

        # Write template
        output_path.write_text(template, encoding='utf-8')

        logger.info(f"Created subagent template: {output_path}")

        return output_path


class SubAgentConfigLoader:
    """Loads subagent configurations from prompts directory.

    Search order (highest to lowest priority):
    1. Built-in: src/prompts/subagents/*.py (Python constants)
    2. Legacy: ./.claude/agents/*.md (Markdown files, deprecated)
    3. User: ~/.claude/agents/*.md (Markdown files, deprecated)
    
    Note: Markdown format is deprecated. Use Python constants in src/prompts/subagents/
    """

    def __init__(self, working_directory: Optional[Path] = None):
        """Initialize loader.

        Args:
            working_directory: Project directory (default: current directory)
        """
        self.working_directory = working_directory or Path.cwd()
        self.loaded_configs: Dict[str, SubAgentConfig] = {}

    def discover_all(self) -> Dict[str, SubAgentConfig]:
        """Discover all subagent configurations.

        Returns:
            Dict mapping subagent names to configs

        Example:
            >>> loader = SubAgentConfigLoader()
            >>> configs = loader.discover_all()
            >>> print(list(configs.keys()))
            ['code-reviewer', 'test-writer', 'doc-writer']
        """
        configs: Dict[str, SubAgentConfig] = {}

        # Load from built-in prompts (highest priority)
        builtin_configs = self._load_from_python_prompts()
        builtin_names = set(builtin_configs.keys())  # Track built-in names
        configs.update(builtin_configs)
        if builtin_configs:
            logger.info(f"Loaded {len(builtin_configs)} built-in subagent(s) from src/prompts/subagents/")

        # Load from user directory (legacy, lower priority)
        user_dir = Path.home() / ".claude" / "agents"
        if user_dir.exists():
            user_configs = self._load_from_directory(user_dir)
            added_count = 0
            for name, config in user_configs.items():
                if name not in builtin_names:  # Don't override built-in
                    configs[name] = config
                    added_count += 1
                else:
                    logger.debug(f"Skipping user subagent '{name}' (overridden by built-in)")
            if added_count > 0:
                logger.warning(f"Loaded {added_count} subagent(s) from legacy user directory (consider migrating to src/prompts/subagents/)")

        # Load from project directory (legacy, can override user but not built-in)
        project_dir = self.working_directory / ".claude" / "agents"
        if project_dir.exists():
            project_configs = self._load_from_directory(project_dir)
            added_count = 0
            for name, config in project_configs.items():
                if name not in builtin_names:  # Don't override built-in
                    configs[name] = config
                    added_count += 1
                else:
                    logger.debug(f"Skipping project subagent '{name}' (overridden by built-in)")
            if added_count > 0:
                logger.warning(f"Loaded {added_count} subagent(s) from legacy project directory (consider migrating to src/prompts/subagents/)")

        # Cache loaded configs
        self.loaded_configs = configs

        logger.info(f"Total subagents discovered: {len(configs)}")
        return configs

    def _load_from_python_prompts(self) -> Dict[str, SubAgentConfig]:
        """Load subagent prompts from Python constants in src/prompts/subagents/.

        Returns:
            Dict mapping subagent names to configs
        """
        configs = {}

        try:
            # Import the subagent prompts module
            from src.prompts.subagents import (
                CODE_REVIEWER_PROMPT,
                TEST_WRITER_PROMPT,
                DOC_WRITER_PROMPT,
            )

            # Define subagent configurations
            subagents = [
                {
                    'name': 'code-reviewer',
                    'description': 'Expert code reviewer analyzing code quality, security vulnerabilities, performance issues, and best practices with verification-first methodology',
                    'prompt': CODE_REVIEWER_PROMPT,
                },
                {
                    'name': 'test-writer',
                    'description': 'Expert test engineer creating comprehensive test suites with unit tests, integration tests, and edge case coverage',
                    'prompt': TEST_WRITER_PROMPT,
                },
                {
                    'name': 'doc-writer',
                    'description': 'Expert technical writer creating clear, comprehensive documentation',
                    'prompt': DOC_WRITER_PROMPT,
                },
            ]

            # Create SubAgentConfig objects
            for subagent in subagents:
                config = SubAgentConfig(
                    name=subagent['name'],
                    description=subagent['description'],
                    system_prompt=subagent['prompt'],
                    tools=None,  # Inherit all tools
                    model=None,  # Inherit model
                    context_window=None,  # Inherit context window
                    config_path=None,  # No file path for Python constants
                    metadata={'source': 'builtin'}
                )
                configs[config.name] = config
                logger.debug(f"Loaded built-in subagent: {config.name}")

        except ImportError as e:
            logger.warning(f"Failed to import subagent prompts: {e}")
        except Exception as e:
            logger.error(f"Error loading Python subagent prompts: {e}")

        return configs

    def _load_from_directory(self, directory: Path) -> Dict[str, SubAgentConfig]:
        """Load all .md files from a directory (legacy format).

        Args:
            directory: Directory to scan

        Returns:
            Dict mapping subagent names to configs
        """
        configs = {}

        # Find all .md files
        for md_file in directory.glob("*.md"):
            try:
                config = SubAgentConfig.from_file(md_file)
                configs[config.name] = config
                logger.debug(f"Loaded subagent: {config.name} from {md_file}")
            except Exception as e:
                logger.error(f"Failed to load subagent from {md_file}: {e}")
                # Continue loading other configs

        return configs

    def load(self, name: str) -> Optional[SubAgentConfig]:
        """Load a specific subagent by name.

        Args:
            name: Subagent name

        Returns:
            SubAgentConfig if found, None otherwise

        Example:
            >>> loader = SubAgentConfigLoader()
            >>> config = loader.load("code-reviewer")
            >>> if config:
            ...     print(config.description)
        """
        # Check cache first
        if name in self.loaded_configs:
            return self.loaded_configs[name]

        # Discover all configs
        self.discover_all()

        # Return requested config
        return self.loaded_configs.get(name)

    def reload(self) -> Dict[str, SubAgentConfig]:
        """Reload all configurations (clears cache).

        Returns:
            Dict mapping subagent names to configs
        """
        self.loaded_configs.clear()
        return self.discover_all()

    def get_all_names(self) -> List[str]:
        """Get names of all discovered subagents.

        Returns:
            List of subagent names
        """
        if not self.loaded_configs:
            self.discover_all()
        return list(self.loaded_configs.keys())
