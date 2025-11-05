"""
ClarAIty Agent Hook

Integrates ClarAIty blueprint generation into the agent's task execution flow.

This hook:
1. Intercepts complex tasks before execution
2. Generates architecture blueprint using LLM
3. Shows interactive approval UI to user
4. Blocks code generation until user approves
5. Passes approved blueprint context to execution
"""

import logging
from typing import Optional, Dict, Any, Tuple
from dataclasses import dataclass

from ..config import get_config, ClarityConfig
from ..core.generator import ClarityGenerator, ClarityGeneratorError
from ..core.blueprint import Blueprint
from ..ui.approval import ApprovalServer, ApprovalDecision
from ..core.database import ClarityDB

logger = logging.getLogger(__name__)


@dataclass
class ClarityHookResult:
    """Result of ClarAIty hook execution."""
    should_proceed: bool
    """Whether task execution should proceed"""

    blueprint: Optional[Blueprint] = None
    """Generated blueprint (if any)"""

    decision: Optional[str] = None
    """User decision (approved/rejected/skipped)"""

    feedback: Optional[str] = None
    """User feedback (for rejections)"""

    modified_task: Optional[str] = None
    """Modified task description (if user provided feedback)"""


class ClarityAgentHook:
    """
    Hook for integrating ClarAIty into the coding agent.

    This hook intercepts task execution to generate architecture blueprints
    and get user approval before code generation begins.
    """

    def __init__(
        self,
        config: Optional[ClarityConfig] = None,
        generator: Optional[ClarityGenerator] = None,
        clarity_db: Optional[ClarityDB] = None
    ):
        """
        Initialize ClarAIty hook.

        Args:
            config: ClarityConfig instance (uses global if None)
            generator: ClarityGenerator instance (creates if None)
            clarity_db: ClarityDB instance (creates if None)
        """
        self.config = config or get_config()
        self.generator = generator
        self.clarity_db = clarity_db

        # Lazy initialization
        if self.generator is None and self.config.enable_generate_mode:
            self.generator = ClarityGenerator(
                model_name=self.config.llm_model,
                base_url=self.config.llm_base_url,
                api_key_env=self.config.llm_api_key_env
            )

        if self.clarity_db is None:
            from pathlib import Path
            db_path = Path(self.config.db_path)
            if db_path.exists():
                self.clarity_db = ClarityDB(str(db_path))

        logger.info(f"ClarityAgentHook initialized: enabled={self.config.enabled}, mode={self.config.mode}")

    def should_use_clarity(
        self,
        task_description: str,
        task_type: str,
        metadata: Dict[str, Any]
    ) -> bool:
        """
        Determine if ClarAIty should be used for this task.

        Decision logic:
        - If disabled: No
        - If mode='manual': No (user must explicitly enable)
        - If mode='always': Yes (always show blueprint)
        - If mode='auto': Analyze complexity

        Args:
            task_description: Task description
            task_type: Task type (implement, debug, etc.)
            metadata: Additional metadata

        Returns:
            True if ClarAIty should be used
        """
        # Check if enabled
        if not self.config.enabled:
            logger.debug("ClarAIty disabled, skipping")
            return False

        # Check mode
        if self.config.mode == "manual":
            logger.debug("ClarAIty in manual mode, skipping (user must explicitly enable)")
            return False

        if self.config.mode == "always":
            logger.info("ClarAIty mode=always, using blueprint")
            return True

        # Auto mode: Analyze complexity
        if self.config.mode == "auto":
            return self._analyze_complexity(task_description, task_type, metadata)

        logger.warning(f"Unknown ClarAIty mode: {self.config.mode}, skipping")
        return False

    def _analyze_complexity(
        self,
        task_description: str,
        task_type: str,
        metadata: Dict[str, Any]
    ) -> bool:
        """
        Analyze task complexity to determine if blueprint is needed.

        Heuristics:
        - Long tasks (> 200 words) → Complex
        - Multiple components/files mentioned → Complex
        - Keywords: "architecture", "system", "integrate", "build" → Complex
        - Task types: "implement" → Complex, "explain" → Simple

        Args:
            task_description: Task description
            task_type: Task type
            metadata: Additional metadata

        Returns:
            True if task appears complex enough for blueprint
        """
        # Simple task types
        simple_types = ["explain", "debug", "document", "review"]
        if task_type in simple_types:
            logger.debug(f"Task type '{task_type}' is simple, skipping blueprint")
            return False

        # Count words
        word_count = len(task_description.split())
        if word_count > 200:
            logger.info(f"Task has {word_count} words (> 200), using blueprint")
            return True

        # Check for complexity keywords
        complexity_keywords = [
            "architecture", "system", "integrate", "build", "implement",
            "create", "design", "multiple", "components", "modules",
            "server", "api", "database", "ui", "frontend", "backend"
        ]

        description_lower = task_description.lower()
        keyword_matches = sum(1 for kw in complexity_keywords if kw in description_lower)

        if keyword_matches >= 3:
            logger.info(f"Task has {keyword_matches} complexity keywords, using blueprint")
            return True

        # Check for multiple files/components
        if any(indicator in description_lower for indicator in ["multiple files", "several files", "multiple components"]):
            logger.info("Task mentions multiple files/components, using blueprint")
            return True

        logger.debug("Task appears simple, skipping blueprint")
        return False

    def intercept_task(
        self,
        task_description: str,
        task_type: str,
        metadata: Dict[str, Any]
    ) -> ClarityHookResult:
        """
        Intercept task execution and generate blueprint if needed.

        This is the main entry point for the hook. It:
        1. Determines if ClarAIty should be used
        2. Generates blueprint if needed
        3. Shows approval UI
        4. Returns result with user decision

        Args:
            task_description: Task description
            task_type: Task type
            metadata: Additional metadata

        Returns:
            ClarityHookResult with decision and blueprint
        """
        # Check if we should use ClarAIty
        if not self.should_use_clarity(task_description, task_type, metadata):
            return ClarityHookResult(
                should_proceed=True,
                decision="skipped"
            )

        # Generate blueprint
        try:
            print("\n" + "="*80)
            print("🎯 ClarAIty: Generating Architecture Blueprint")
            print("="*80 + "\n")

            # Get codebase context if available
            codebase_context = self._get_codebase_context()

            # Generate blueprint
            blueprint = self.generator.generate_blueprint(
                task_description=task_description,
                codebase_context=codebase_context
            )

            print(f"✅ Blueprint generated: {len(blueprint.components)} components, "
                  f"{len(blueprint.design_decisions)} decisions\n")

            # Show approval UI
            print("🖼️  Launching approval UI...\n")

            approval_server = ApprovalServer(
                blueprint=blueprint,
                port=self.config.approval_ui_port
            )

            decision_result = approval_server.start_and_wait(
                auto_open=self.config.auto_open_browser
            )

            # Process decision
            if decision_result.approved:
                print("\n✅ Blueprint APPROVED - Proceeding with code generation\n")

                # Store blueprint in database (for Document Existing mode)
                if self.clarity_db:
                    self._store_blueprint(blueprint)

                return ClarityHookResult(
                    should_proceed=True,
                    blueprint=blueprint,
                    decision="approved"
                )
            else:
                print("\n❌ Blueprint REJECTED\n")

                if decision_result.feedback:
                    print(f"User feedback: {decision_result.feedback}\n")

                    # Ask if user wants to regenerate with feedback
                    print("Options:")
                    print("  1. Regenerate blueprint with feedback")
                    print("  2. Abort task")

                    # For now, abort (in future, could support regeneration)
                    return ClarityHookResult(
                        should_proceed=False,
                        blueprint=blueprint,
                        decision="rejected",
                        feedback=decision_result.feedback
                    )
                else:
                    return ClarityHookResult(
                        should_proceed=False,
                        blueprint=blueprint,
                        decision="rejected"
                    )

        except ClarityGeneratorError as e:
            logger.error(f"Blueprint generation failed: {e}")
            print(f"\n⚠️  Blueprint generation failed: {e}")
            print("Proceeding without blueprint...\n")

            return ClarityHookResult(
                should_proceed=True,
                decision="error"
            )

        except Exception as e:
            logger.error(f"ClarAIty hook error: {e}", exc_info=True)
            print(f"\n⚠️  ClarAIty error: {e}")
            print("Proceeding without blueprint...\n")

            return ClarityHookResult(
                should_proceed=True,
                decision="error"
            )

    def _get_codebase_context(self) -> str:
        """
        Get codebase context for blueprint generation.

        Queries clarity database for existing components and patterns.

        Returns:
            Codebase context string
        """
        if not self.clarity_db:
            return ""

        try:
            # Get component statistics
            stats = self.clarity_db.get_statistics()

            # Get recent components
            components = self.clarity_db.get_all_components()

            # Build context
            context_parts = [
                f"Existing codebase has {stats.get('total_components', 0)} components.",
                f"",
                "Key components:"
            ]

            # Add top components by layer
            layers = {}
            for comp in components[:30]:  # Top 30 components
                layer = comp.get('layer', 'unknown')
                if layer not in layers:
                    layers[layer] = []
                layers[layer].append(comp['name'])

            for layer, comps in layers.items():
                context_parts.append(f"  {layer}: {', '.join(comps[:5])}")

            return "\n".join(context_parts)

        except Exception as e:
            logger.warning(f"Error getting codebase context: {e}")
            return ""

    def _store_blueprint(self, blueprint: Blueprint):
        """
        Store blueprint in database for Document Existing mode.

        This enables tracking what was planned vs what was implemented.

        Args:
            blueprint: Blueprint to store
        """
        if not self.clarity_db:
            return

        try:
            # Store components
            for component in blueprint.components:
                self.clarity_db.add_component(
                    name=component.name,
                    component_type=component.type,
                    purpose=component.purpose,
                    layer=component.layer
                )

            logger.info(f"Stored blueprint: {len(blueprint.components)} components")

        except Exception as e:
            logger.warning(f"Error storing blueprint: {e}")


# Global hook instance (lazy initialization)
_global_hook: Optional[ClarityAgentHook] = None


def get_clarity_hook() -> ClarityAgentHook:
    """
    Get global ClarityAgentHook instance.

    Returns:
        Global hook instance
    """
    global _global_hook

    if _global_hook is None:
        _global_hook = ClarityAgentHook()

    return _global_hook


def should_use_clarity(
    task_description: str,
    task_type: str = "implement",
    metadata: Optional[Dict[str, Any]] = None
) -> bool:
    """
    Convenience function to check if ClarAIty should be used.

    Args:
        task_description: Task description
        task_type: Task type
        metadata: Additional metadata

    Returns:
        True if ClarAIty should be used
    """
    hook = get_clarity_hook()
    return hook.should_use_clarity(
        task_description,
        task_type,
        metadata or {}
    )
