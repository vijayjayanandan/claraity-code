"""SubAgentManager for delegation and coordination.

The manager orchestrates multiple subagents:
- Loads and caches subagent configurations
- Provides automatic delegation based on task description
- Supports explicit delegation by subagent name
- Enables parallel execution of multiple subagents
- Aggregates results from subagent executions

Example:
    >>> manager = SubAgentManager(main_agent)
    >>> manager.discover_subagents()
    >>>
    >>> # Explicit delegation
    >>> result = manager.delegate("code-reviewer", "Review src/api.py")
    >>>
    >>> # Automatic delegation
    >>> result = manager.auto_delegate("Find security issues in auth module")
    >>>
    >>> # Parallel execution
    >>> tasks = [
    ...     ("code-reviewer", "Review src/api.py"),
    ...     ("test-writer", "Write tests for src/api.py")
    ... ]
    >>> results = manager.execute_parallel(tasks)
"""

from typing import Dict, List, Optional, Tuple, Any, TYPE_CHECKING
from pathlib import Path
import logging
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import dataclass, field

if TYPE_CHECKING:
    from src.core.agent_interface import AgentInterface
    from src.subagents.config import SubAgentConfig
    from src.subagents.subagent import SubAgent, SubAgentResult

from src.subagents.config import SubAgentConfigLoader
from src.subagents.subagent import SubAgent
from src.platform import remove_emojis

logger = logging.getLogger(__name__)


@dataclass
class DelegationResult:
    """Result from delegating to one or more subagents.

    Attributes:
        success: Whether all delegations succeeded
        subagent_results: Results from each subagent execution
        total_time: Total execution time in seconds
        metadata: Additional information about the delegation
    """
    success: bool
    subagent_results: List['SubAgentResult']
    total_time: float
    metadata: Dict[str, Any] = field(default_factory=dict)

    def __str__(self) -> str:
        """Human-readable representation."""
        status = "[OK] SUCCESS" if self.success else "[FAIL] FAILED"
        lines = [
            f"Delegation Result: {status}",
            f"Subagents Used: {len(self.subagent_results)}",
            f"Total Time: {self.total_time:.2f}s",
        ]

        for i, result in enumerate(self.subagent_results, 1):
            status_marker = "[OK]" if result.success else "[FAIL]"
            lines.append(
                f"  {i}. [{result.subagent_name}] {status_marker} "
                f"({result.execution_time:.2f}s)"
            )

        return "\n".join(lines)


class SubAgentManager:
    """Manager for coordinating multiple subagents.

    The SubAgentManager handles:
    - Discovery and loading of subagent configurations
    - Lazy instantiation and caching of subagent instances
    - Automatic delegation based on task description
    - Explicit delegation by subagent name
    - Parallel execution of multiple subagents
    - Result aggregation and error handling

    Subagents are loaded from:
    1. Project directory: .claude/agents/*.md (highest priority)
    2. User directory: ~/.claude/agents/*.md (lower priority)

    Example:
        >>> manager = SubAgentManager(main_agent, working_directory=Path.cwd())
        >>> manager.discover_subagents()
        >>>
        >>> # List available subagents
        >>> print(manager.get_available_subagents())
        ['code-reviewer', 'test-writer', 'doc-writer']
        >>>
        >>> # Delegate to specific subagent
        >>> result = manager.delegate("code-reviewer", "Review api.py for bugs")
        >>> print(result.output)
    """

    def __init__(
        self,
        main_agent: 'AgentInterface',
        working_directory: Optional[Path] = None,
        max_parallel_workers: int = 4,
        enable_auto_delegation: bool = True
    ):
        """Initialize SubAgentManager.

        Args:
            main_agent: Main agent instance (implements AgentInterface)
            working_directory: Project directory (default: current directory)
            max_parallel_workers: Maximum concurrent subagent executions
            enable_auto_delegation: Enable automatic delegation based on task
        """
        self.main_agent = main_agent
        self.working_directory = working_directory or Path.cwd()
        self.max_parallel_workers = max_parallel_workers
        self.enable_auto_delegation = enable_auto_delegation

        # Configuration loader
        self.config_loader = SubAgentConfigLoader(self.working_directory)

        # Loaded configurations and cached instances
        self.configs: Dict[str, 'SubAgentConfig'] = {}
        self.subagent_instances: Dict[str, 'SubAgent'] = {}

        # Delegation statistics
        self.delegation_count: Dict[str, int] = {}
        self.total_delegations = 0

        logger.info(
            f"SubAgentManager initialized "
            f"(max_workers={max_parallel_workers}, auto_delegation={enable_auto_delegation})"
        )

    def discover_subagents(self) -> Dict[str, 'SubAgentConfig']:
        """Discover all available subagent configurations.

        Loads configurations from:
        1. User directory: ~/.claude/agents/*.md
        2. Project directory: .claude/agents/*.md (overrides user configs)

        Returns:
            Dict mapping subagent names to configurations

        Example:
            >>> manager.discover_subagents()
            {'code-reviewer': SubAgentConfig(...), 'test-writer': SubAgentConfig(...)}
        """
        self.configs = self.config_loader.discover_all()

        logger.info(f"Discovered {len(self.configs)} subagent(s): {list(self.configs.keys())}")

        return self.configs

    def reload_subagents(self) -> Dict[str, 'SubAgentConfig']:
        """Reload all configurations and clear cached instances.

        Useful when subagent configurations have been modified.

        Returns:
            Dict mapping subagent names to configurations
        """
        # Clear cached instances
        self.subagent_instances.clear()

        # Reload configurations
        self.configs = self.config_loader.reload()

        logger.info(f"Reloaded {len(self.configs)} subagent(s)")

        return self.configs

    def get_subagent(self, name: str) -> Optional['SubAgent']:
        """Get or create a subagent instance.

        Subagent instances are cached for reuse.

        Args:
            name: Subagent name (e.g., "code-reviewer")

        Returns:
            SubAgent instance if found, None otherwise

        Example:
            >>> subagent = manager.get_subagent("code-reviewer")
            >>> result = subagent.execute("Review api.py")
        """
        # Check cache first
        if name in self.subagent_instances:
            return self.subagent_instances[name]

        # Get configuration
        config = self.configs.get(name)
        if not config:
            logger.warning(f"Subagent '{name}' not found. Available: {list(self.configs.keys())}")
            return None

        # Create instance
        try:
            subagent = SubAgent(
                config=config,
                main_agent=self.main_agent,
            )

            # Cache instance
            self.subagent_instances[name] = subagent

            logger.debug(f"Created subagent instance: {name}")

            return subagent

        except Exception as e:
            logger.error(f"Failed to create subagent '{name}': {e}")
            return None

    def delegate(
        self,
        subagent_name: str,
        task_description: str,
        context: Optional[Dict[str, Any]] = None,
        max_iterations: int = 50
    ) -> Optional['SubAgentResult']:
        """Delegate task to a specific subagent.

        Args:
            subagent_name: Name of the subagent to use
            task_description: Task to execute
            context: Optional additional context
            max_iterations: Maximum tool-calling iterations

        Returns:
            SubAgentResult if successful, None if subagent not found

        Example:
            >>> result = manager.delegate(
            ...     "code-reviewer",
            ...     "Review src/api.py for security issues"
            ... )
            >>> if result and result.success:
            ...     print(result.output)
        """
        subagent = self.get_subagent(subagent_name)
        if not subagent:
            return None

        # Track delegation
        self.total_delegations += 1
        self.delegation_count[subagent_name] = self.delegation_count.get(subagent_name, 0) + 1

        logger.info(f"Delegating to subagent '{subagent_name}': {task_description[:100]}...")

        # Execute task
        result = subagent.execute(
            task_description=task_description,
            context=context,
            max_iterations=max_iterations
        )

        logger.info(
            f"Subagent '{subagent_name}' completed: "
            f"{'[OK] success' if result.success else '[FAIL] failed'} "
            f"({result.execution_time:.2f}s)"
        )

        return result

    def auto_delegate(
        self,
        task_description: str,
        context: Optional[Dict[str, Any]] = None,
        max_iterations: int = 50
    ) -> Optional['SubAgentResult']:
        """Automatically select and delegate to best subagent.

        Uses subagent descriptions to find the best match for the task.

        Args:
            task_description: Task to execute
            context: Optional additional context
            max_iterations: Maximum tool-calling iterations

        Returns:
            SubAgentResult from the selected subagent, None if no match

        Example:
            >>> result = manager.auto_delegate(
            ...     "Find security vulnerabilities in authentication module"
            ... )
            >>> # Automatically selects "code-reviewer" or "security-auditor"
        """
        if not self.enable_auto_delegation:
            logger.warning("Auto-delegation is disabled")
            return None

        # Find best subagent based on description similarity
        best_subagent = self._select_best_subagent(task_description)

        if not best_subagent:
            logger.info("No suitable subagent found for auto-delegation")
            return None

        logger.info(f"Auto-delegating to subagent '{best_subagent}'")

        return self.delegate(
            subagent_name=best_subagent,
            task_description=task_description,
            context=context,
            max_iterations=max_iterations
        )

    def execute_parallel(
        self,
        tasks: List[Tuple[str, str, Optional[Dict[str, Any]]]],
        max_iterations: int = 50
    ) -> DelegationResult:
        """Execute multiple subagent tasks in parallel.

        Args:
            tasks: List of (subagent_name, task_description, context) tuples
            max_iterations: Maximum tool-calling iterations per subagent

        Returns:
            DelegationResult with all subagent results

        Example:
            >>> tasks = [
            ...     ("code-reviewer", "Review src/api.py", None),
            ...     ("test-writer", "Write tests for src/api.py", None),
            ...     ("doc-writer", "Document src/api.py", None)
            ... ]
            >>> result = manager.execute_parallel(tasks)
            >>> print(f"All succeeded: {result.success}")
        """
        start_time = time.time()
        results: List['SubAgentResult'] = []

        logger.info(f"Executing {len(tasks)} subagent tasks in parallel")

        with ThreadPoolExecutor(max_workers=self.max_parallel_workers) as executor:
            # Submit all tasks
            future_to_task = {}
            for subagent_name, task_desc, context in tasks:
                future = executor.submit(
                    self.delegate,
                    subagent_name,
                    task_desc,
                    context,
                    max_iterations
                )
                future_to_task[future] = (subagent_name, task_desc)

            # Collect results as they complete
            for future in as_completed(future_to_task):
                subagent_name, task_desc = future_to_task[future]
                try:
                    result = future.result()
                    if result:
                        results.append(result)
                    else:
                        logger.error(f"Subagent '{subagent_name}' returned None")
                except Exception as e:
                    logger.error(f"Subagent '{subagent_name}' raised exception: {e}")

        total_time = time.time() - start_time
        success = all(r.success for r in results) and len(results) == len(tasks)

        delegation_result = DelegationResult(
            success=success,
            subagent_results=results,
            total_time=total_time,
            metadata={
                "tasks_submitted": len(tasks),
                "tasks_completed": len(results),
                "parallel_workers": self.max_parallel_workers
            }
        )

        logger.info(
            f"Parallel execution complete: "
            f"{'[OK] all succeeded' if success else '[FAIL] some failed'} "
            f"({total_time:.2f}s total)"
        )

        return delegation_result

    def _select_best_subagent(self, task_description: str) -> Optional[str]:
        """Select the best subagent for a task based on description similarity.

        Uses simple keyword matching between task and subagent descriptions.
        Future enhancement: Use semantic similarity (embeddings).

        Args:
            task_description: Task to execute

        Returns:
            Subagent name if match found, None otherwise
        """
        task_lower = task_description.lower()

        # Keyword-based matching
        best_match = None
        best_score = 0

        for name, config in self.configs.items():
            description_lower = config.description.lower()

            # Count matching keywords
            score = 0

            # Split task and description into words
            task_words = set(task_lower.split())
            desc_words = set(description_lower.split())

            # Count common words (excluding stopwords)
            common_words = task_words & desc_words
            score += len(common_words)

            # Bonus for exact phrase matches
            if any(phrase in task_lower for phrase in description_lower.split(',')):
                score += 5

            if score > best_score:
                best_score = score
                best_match = name

        if best_score > 0:
            logger.debug(
                f"Best subagent for task: '{best_match}' (score={best_score})"
            )
            return best_match

        return None

    def get_available_subagents(self) -> List[str]:
        """Get list of all available subagent names.

        Returns:
            List of subagent names

        Example:
            >>> manager.get_available_subagents()
            ['code-reviewer', 'test-writer', 'doc-writer']
        """
        return list(self.configs.keys())

    def get_subagent_info(self, name: str) -> Optional[Dict[str, Any]]:
        """Get information about a subagent.

        Args:
            name: Subagent name

        Returns:
            Dict with subagent info, None if not found

        Example:
            >>> info = manager.get_subagent_info("code-reviewer")
            >>> print(info['description'])
            'Expert code reviewer for quality and security'
        """
        config = self.configs.get(name)
        if not config:
            return None

        return {
            "name": config.name,
            "description": config.description,
            "tools": config.tools or "All tools inherited",
            "model": config.model or "Inherited from main agent",
            "context_window": config.context_window or "Inherited from main agent",
            "config_path": str(config.config_path) if config.config_path else None,
            "delegation_count": self.delegation_count.get(name, 0)
        }

    def get_statistics(self) -> Dict[str, Any]:
        """Get delegation statistics.

        Returns:
            Statistics dictionary

        Example:
            >>> stats = manager.get_statistics()
            >>> print(f"Total delegations: {stats['total_delegations']}")
        """
        return {
            "total_delegations": self.total_delegations,
            "subagents_available": len(self.configs),
            "subagents_used": len(self.delegation_count),
            "delegation_by_subagent": dict(self.delegation_count),
            "cached_instances": len(self.subagent_instances),
            "max_parallel_workers": self.max_parallel_workers,
            "auto_delegation_enabled": self.enable_auto_delegation
        }
