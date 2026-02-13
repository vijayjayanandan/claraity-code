"""Comprehensive tests for SubAgentConfig and SubAgentConfigLoader."""

import pytest
from pathlib import Path
from unittest.mock import Mock, patch

from src.subagents.config import SubAgentConfig, SubAgentConfigLoader


@pytest.fixture
def temp_config_dir(tmp_path):
    """Create temporary directory for config files."""
    config_dir = tmp_path / ".clarity" / "agents"
    config_dir.mkdir(parents=True)
    return config_dir


@pytest.fixture
def valid_config_content():
    """Valid subagent configuration content."""
    return """---
name: test-agent
description: Test subagent for unit testing
tools: Read, Write, Edit
model: sonnet
context_window: 8192
---

# Test Agent

You are a test subagent for unit testing.

## Responsibilities:
- Execute test tasks
- Validate functionality
"""


@pytest.fixture
def minimal_config_content():
    """Minimal valid configuration (only required fields)."""
    return """---
name: minimal-agent
description: Minimal test agent
---

You are a minimal test agent.
"""


class TestSubAgentConfigValidation:
    """Test SubAgentConfig validation."""

    def test_valid_config_creation(self):
        """Test creating a valid SubAgentConfig."""
        config = SubAgentConfig(
            name="test-agent",
            description="Test subagent",
            system_prompt="You are a test agent.",
            tools=["Read", "Write"],
            model="sonnet",
            context_window=8192
        )

        assert config.name == "test-agent"
        assert config.description == "Test subagent"
        assert config.system_prompt == "You are a test agent."
        assert config.tools == ["Read", "Write"]
        assert config.model == "sonnet"
        assert config.context_window == 8192

    def test_invalid_name_format(self):
        """Test that invalid name formats raise ValueError."""
        # Uppercase not allowed
        with pytest.raises(ValueError, match="Invalid subagent name"):
            SubAgentConfig(
                name="TestAgent",
                description="Test",
                system_prompt="Prompt"
            )

        # Spaces not allowed
        with pytest.raises(ValueError, match="Invalid subagent name"):
            SubAgentConfig(
                name="test agent",
                description="Test",
                system_prompt="Prompt"
            )

        # Underscores not allowed
        with pytest.raises(ValueError, match="Invalid subagent name"):
            SubAgentConfig(
                name="test_agent",
                description="Test",
                system_prompt="Prompt"
            )

    def test_empty_description(self):
        """Test that empty description raises ValueError."""
        with pytest.raises(ValueError, match="must have a description"):
            SubAgentConfig(
                name="test-agent",
                description="",
                system_prompt="Prompt"
            )

        # Whitespace-only description
        with pytest.raises(ValueError, match="must have a description"):
            SubAgentConfig(
                name="test-agent",
                description="   ",
                system_prompt="Prompt"
            )

    def test_empty_system_prompt(self):
        """Test that empty system prompt raises ValueError."""
        with pytest.raises(ValueError, match="must have a system prompt"):
            SubAgentConfig(
                name="test-agent",
                description="Test",
                system_prompt=""
            )

        # Whitespace-only prompt
        with pytest.raises(ValueError, match="must have a system prompt"):
            SubAgentConfig(
                name="test-agent",
                description="Test",
                system_prompt="   "
            )

    def test_tools_list_normalization(self):
        """Test that tools list is normalized (whitespace removed)."""
        config = SubAgentConfig(
            name="test-agent",
            description="Test",
            system_prompt="Prompt",
            tools=["Read", "  Write  ", "", "Edit", "  "]
        )

        # Empty strings should be removed
        assert config.tools == ["Read", "Write", "Edit"]


class TestSubAgentConfigFileLoading:
    """Test SubAgentConfig.from_file() functionality."""

    def test_load_valid_config(self, temp_config_dir, valid_config_content):
        """Test loading a valid configuration file."""
        config_file = temp_config_dir / "test-agent.md"
        config_file.write_text(valid_config_content)

        config = SubAgentConfig.from_file(config_file)

        assert config.name == "test-agent"
        assert config.description == "Test subagent for unit testing"
        assert "You are a test subagent" in config.system_prompt
        assert config.tools == ["Read", "Write", "Edit"]
        assert config.model == "sonnet"
        assert config.context_window == 8192
        assert config.config_path == config_file

    def test_load_minimal_config(self, temp_config_dir, minimal_config_content):
        """Test loading minimal configuration (only required fields)."""
        config_file = temp_config_dir / "minimal-agent.md"
        config_file.write_text(minimal_config_content)

        config = SubAgentConfig.from_file(config_file)

        assert config.name == "minimal-agent"
        assert config.description == "Minimal test agent"
        assert "You are a minimal test agent" in config.system_prompt
        assert config.tools is None
        assert config.model is None
        assert config.context_window is None

    def test_load_file_not_found(self, temp_config_dir):
        """Test loading non-existent file raises FileNotFoundError."""
        non_existent = temp_config_dir / "does-not-exist.md"

        with pytest.raises(FileNotFoundError, match="Configuration file not found"):
            SubAgentConfig.from_file(non_existent)

    def test_load_missing_required_fields(self, temp_config_dir):
        """Test that missing required fields raise ValueError."""
        # Missing 'name'
        config_file = temp_config_dir / "missing-name.md"
        config_file.write_text("""---
description: Test
---

Prompt
""")

        with pytest.raises(ValueError, match="missing required field"):
            SubAgentConfig.from_file(config_file)

        # Missing 'description'
        config_file2 = temp_config_dir / "missing-description.md"
        config_file2.write_text("""---
name: test
---

Prompt
""")

        with pytest.raises(ValueError, match="missing required field"):
            SubAgentConfig.from_file(config_file2)

    def test_load_invalid_frontmatter(self, temp_config_dir):
        """Test that invalid YAML frontmatter raises ValueError."""
        config_file = temp_config_dir / "invalid-yaml.md"
        config_file.write_text("""---
name: test
description: Test
invalid_yaml: [unclosed list
---

Prompt
""")

        with pytest.raises(ValueError, match="Invalid YAML frontmatter"):
            SubAgentConfig.from_file(config_file)

    def test_load_tools_as_string(self, temp_config_dir):
        """Test parsing tools as comma-separated string."""
        config_file = temp_config_dir / "tools-string.md"
        config_file.write_text("""---
name: tools-test
description: Test tools parsing
tools: Read, Write, Edit, SearchCode
---

Prompt
""")

        config = SubAgentConfig.from_file(config_file)

        assert config.tools == ["Read", "Write", "Edit", "SearchCode"]

    def test_load_tools_as_list(self, temp_config_dir):
        """Test parsing tools as YAML list."""
        config_file = temp_config_dir / "tools-list.md"
        config_file.write_text("""---
name: tools-test
description: Test tools parsing
tools:
  - Read
  - Write
  - Edit
---

Prompt
""")

        config = SubAgentConfig.from_file(config_file)

        assert config.tools == ["Read", "Write", "Edit"]

    def test_load_model_inherit(self, temp_config_dir):
        """Test that 'model: inherit' is converted to None."""
        config_file = temp_config_dir / "model-inherit.md"
        config_file.write_text("""---
name: inherit-test
description: Test model inheritance
model: inherit
---

Prompt
""")

        config = SubAgentConfig.from_file(config_file)

        assert config.model is None

    def test_load_invalid_context_window(self, temp_config_dir):
        """Test that invalid context_window raises ValueError."""
        config_file = temp_config_dir / "invalid-context.md"
        config_file.write_text("""---
name: context-test
description: Test context window
context_window: not-a-number
---

Prompt
""")

        with pytest.raises(ValueError, match="context_window.*must be an integer"):
            SubAgentConfig.from_file(config_file)

    def test_load_no_frontmatter(self, temp_config_dir):
        """Test that file without frontmatter raises ValueError."""
        config_file = temp_config_dir / "no-frontmatter.md"
        config_file.write_text("Just a regular markdown file without frontmatter.")

        with pytest.raises(ValueError, match="Expected YAML frontmatter"):
            SubAgentConfig.from_file(config_file)

    def test_load_metadata_extraction(self, temp_config_dir):
        """Test that extra frontmatter fields are stored in metadata."""
        config_file = temp_config_dir / "extra-fields.md"
        config_file.write_text("""---
name: metadata-test
description: Test metadata
author: Test Author
version: 1.0.0
tags:
  - testing
  - example
---

Prompt
""")

        config = SubAgentConfig.from_file(config_file)

        assert config.metadata['author'] == "Test Author"
        assert config.metadata['version'] == "1.0.0"
        assert config.metadata['tags'] == ["testing", "example"]


class TestSubAgentConfigTemplate:
    """Test SubAgentConfig.create_template() functionality."""

    def test_create_template_success(self, temp_config_dir):
        """Test successful template creation."""
        output_path = temp_config_dir / "new-agent.md"

        result_path = SubAgentConfig.create_template(
            name="new-agent",
            description="A new test agent",
            output_path=output_path
        )

        assert result_path == output_path
        assert output_path.exists()

        # Verify template content
        content = output_path.read_text()
        assert "name: new-agent" in content
        assert "description: A new test agent" in content
        assert "tools: Read, Write, Edit" in content
        assert "# New Agent Subagent" in content

    def test_create_template_creates_parent_dirs(self, tmp_path):
        """Test that template creation creates parent directories."""
        nested_path = tmp_path / "deep" / "nested" / "path" / "agent.md"

        SubAgentConfig.create_template(
            name="nested-agent",
            description="Nested agent",
            output_path=nested_path
        )

        assert nested_path.exists()
        assert nested_path.parent.exists()

    def test_create_template_invalid_name(self, temp_config_dir):
        """Test that invalid name raises ValueError."""
        output_path = temp_config_dir / "invalid.md"

        with pytest.raises(ValueError, match="Invalid name"):
            SubAgentConfig.create_template(
                name="Invalid_Name",
                description="Test",
                output_path=output_path
            )


class TestSubAgentConfigLoader:
    """Test SubAgentConfigLoader functionality."""

    def test_discover_all_from_single_directory(self, temp_config_dir):
        """Test discovering all configs from a single directory."""
        # Create multiple config files
        config1 = temp_config_dir / "agent1.md"
        config1.write_text("""---
name: agent1
description: First agent
---
Prompt 1
""")

        config2 = temp_config_dir / "agent2.md"
        config2.write_text("""---
name: agent2
description: Second agent
---
Prompt 2
""")

        loader = SubAgentConfigLoader(working_directory=temp_config_dir.parent.parent)
        configs = loader.discover_all()

        assert len(configs) == 2
        assert "agent1" in configs
        assert "agent2" in configs
        assert configs["agent1"].description == "First agent"
        assert configs["agent2"].description == "Second agent"

    def test_discover_all_hierarchical(self, tmp_path):
        """Test hierarchical loading (user + project)."""
        # Create user directory
        user_dir = tmp_path / "user" / ".clarity" / "agents"
        user_dir.mkdir(parents=True)

        user_config = user_dir / "user-agent.md"
        user_config.write_text("""---
name: user-agent
description: User-level agent
---
User prompt
""")

        # Create project directory
        project_dir = tmp_path / "project" / ".clarity" / "agents"
        project_dir.mkdir(parents=True)

        project_config = project_dir / "project-agent.md"
        project_config.write_text("""---
name: project-agent
description: Project-level agent
---
Project prompt
""")

        # Patch Path.home() to return our temp user directory
        with patch('pathlib.Path.home', return_value=tmp_path / "user"):
            loader = SubAgentConfigLoader(working_directory=tmp_path / "project")
            configs = loader.discover_all()

        assert len(configs) == 2
        assert "user-agent" in configs
        assert "project-agent" in configs

    def test_project_overrides_user(self, tmp_path):
        """Test that project configs override user configs with same name."""
        # Create user directory
        user_dir = tmp_path / "user" / ".clarity" / "agents"
        user_dir.mkdir(parents=True)

        user_config = user_dir / "shared-agent.md"
        user_config.write_text("""---
name: shared-agent
description: User version
---
User prompt
""")

        # Create project directory with same agent name
        project_dir = tmp_path / "project" / ".clarity" / "agents"
        project_dir.mkdir(parents=True)

        project_config = project_dir / "shared-agent.md"
        project_config.write_text("""---
name: shared-agent
description: Project version
---
Project prompt
""")

        # Patch Path.home() to return our temp user directory
        with patch('pathlib.Path.home', return_value=tmp_path / "user"):
            loader = SubAgentConfigLoader(working_directory=tmp_path / "project")
            configs = loader.discover_all()

        # Should have project version, not user version
        assert configs["shared-agent"].description == "Project version"
        assert "Project prompt" in configs["shared-agent"].system_prompt

    def test_load_specific_subagent(self, temp_config_dir):
        """Test loading a specific subagent by name."""
        config_file = temp_config_dir / "specific-agent.md"
        config_file.write_text("""---
name: specific-agent
description: Specific agent
---
Prompt
""")

        loader = SubAgentConfigLoader(working_directory=temp_config_dir.parent.parent)
        config = loader.load("specific-agent")

        assert config is not None
        assert config.name == "specific-agent"
        assert config.description == "Specific agent"

    def test_load_nonexistent_subagent(self, temp_config_dir):
        """Test loading non-existent subagent returns None."""
        loader = SubAgentConfigLoader(working_directory=temp_config_dir.parent.parent)
        config = loader.load("does-not-exist")

        assert config is None

    def test_reload_clears_cache(self, temp_config_dir):
        """Test that reload() clears cache and reloads configs."""
        config_file = temp_config_dir / "cached-agent.md"
        config_file.write_text("""---
name: cached-agent
description: Original description
---
Prompt
""")

        loader = SubAgentConfigLoader(working_directory=temp_config_dir.parent.parent)

        # Load initially
        configs1 = loader.discover_all()
        assert configs1["cached-agent"].description == "Original description"

        # Modify file
        config_file.write_text("""---
name: cached-agent
description: Updated description
---
Prompt
""")

        # Reload
        configs2 = loader.reload()

        # Should have new description
        assert configs2["cached-agent"].description == "Updated description"

    def test_get_all_names(self, temp_config_dir):
        """Test getting all subagent names."""
        # Create config files
        for i in range(3):
            config_file = temp_config_dir / f"agent{i}.md"
            config_file.write_text(f"""---
name: agent{i}
description: Agent {i}
---
Prompt {i}
""")

        loader = SubAgentConfigLoader(working_directory=temp_config_dir.parent.parent)
        names = loader.get_all_names()

        assert len(names) == 3
        assert "agent0" in names
        assert "agent1" in names
        assert "agent2" in names

    def test_loader_handles_invalid_configs(self, temp_config_dir):
        """Test that loader continues loading when encountering invalid configs."""
        # Valid config
        valid_config = temp_config_dir / "valid-agent.md"
        valid_config.write_text("""---
name: valid-agent
description: Valid agent
---
Prompt
""")

        # Invalid config (missing required field)
        invalid_config = temp_config_dir / "invalid-agent.md"
        invalid_config.write_text("""---
name: invalid-agent
---
Prompt
""")

        loader = SubAgentConfigLoader(working_directory=temp_config_dir.parent.parent)
        configs = loader.discover_all()

        # Should load valid config, skip invalid
        assert len(configs) == 1
        assert "valid-agent" in configs
        assert "invalid-agent" not in configs


if __name__ == '__main__':
    pytest.main([__file__, '-v'])
