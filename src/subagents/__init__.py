"""Subagent architecture for specialized AI assistants.

This module provides a subagent system that enables:
- Independent context windows (no main agent pollution)
- Specialized domain expertise
- Tool inheritance and restriction
- Parallel execution for performance
- Configuration-based setup (no code changes)

Components:
- SubAgent: Independent AI assistant with specialized capabilities
- SubAgentConfig: Configuration parser for Markdown + YAML files
- SubAgentManager: Coordinates multiple subagents (to be implemented)
- SubAgentConfigLoader: Discovers and loads configurations

Example:
    >>> from src.subagents import SubAgentConfig, SubAgent
    >>> from src.core.agent import CodingAgent
    >>>
    >>> # Load configuration
    >>> config = SubAgentConfig.from_file(Path(".clarity/agents/code-reviewer.md"))
    >>>
    >>> # Create subagent
    >>> main_agent = CodingAgent()
    >>> subagent = SubAgent(config, main_agent)
    >>>
    >>> # Execute task
    >>> result = subagent.execute("Review src/auth.py for security issues")
    >>> print(result.output)
"""

from src.subagents.subagent import SubAgent, SubAgentResult
from src.subagents.config import SubAgentConfig, SubAgentConfigLoader
from src.subagents.manager import SubAgentManager, DelegationResult

__all__ = [
    'SubAgent',
    'SubAgentResult',
    'SubAgentConfig',
    'SubAgentConfigLoader',
    'SubAgentManager',
    'DelegationResult',
]
