"""
ClarityGenerator - Generate architecture blueprints using LLM

This is the core of Generate Mode: takes a task description and produces
a structured architecture plan BEFORE any code is generated.
"""

import json
import logging
import os
from typing import Optional

from src.llm import LLMBackend, LLMConfig, LLMBackendType, OpenAIBackend
from .blueprint import (
    Blueprint,
    Component,
    DesignDecision,
    FileAction,
    Relationship,
    ComponentType,
    FileActionType,
    RelationType,
)
from .prompts import (
    ARCHITECTURE_GENERATION_SYSTEM_PROMPT,
    generate_architecture_prompt,
    generate_refinement_prompt,
    build_codebase_context,
)

logger = logging.getLogger(__name__)


class ClarityGeneratorError(Exception):
    """Raised when blueprint generation fails."""
    pass


class ClarityGenerator:
    """
    Generate architecture blueprints for code generation tasks.

    This is the "brain" of ClarAIty's Generate Mode.
    """

    def __init__(
        self,
        llm_backend: Optional[LLMBackend] = None,
        model_name: Optional[str] = None,
        base_url: Optional[str] = None,
        api_key: Optional[str] = None,
        api_key_env: str = "OPENAI_API_KEY",
    ):
        """
        Initialize the generator.

        Args:
            llm_backend: Optional LLM backend instance (if None, creates default)
            model_name: Model to use for generation (from .env: LLM_MODEL)
            base_url: Optional base URL for API (from .env: LLM_HOST)
            api_key: Optional API key (from .env: OPENAI_API_KEY)
            api_key_env: Environment variable name for API key (default: OPENAI_API_KEY)
        """
        if llm_backend:
            self.llm = llm_backend
        else:
            # Resolve configuration from .env
            resolved_model_name = model_name or os.getenv("LLM_MODEL")
            resolved_base_url = base_url or os.getenv("LLM_HOST")
            resolved_api_key = api_key or os.getenv(api_key_env)

            if not resolved_model_name:
                raise ValueError("Model name required. Set LLM_MODEL in .env or pass model_name parameter.")
            if not resolved_base_url:
                raise ValueError("Base URL required. Set LLM_HOST in .env or pass base_url parameter.")
            if not resolved_api_key:
                raise ValueError(f"API key required. Set {api_key_env} in .env or pass api_key parameter.")

            # Create default LLM backend (OpenAI-compatible) from .env
            config = LLMConfig(
                backend_type=LLMBackendType.OPENAI,
                model_name=resolved_model_name,
                base_url=resolved_base_url,
                temperature=float(os.getenv("LLM_TEMPERATURE", "0.3")),
                max_tokens=int(os.getenv("LLM_MAX_TOKENS", "4096")),
                top_p=float(os.getenv("LLM_TOP_P", "0.95")),
                context_window=int(os.getenv("MAX_CONTEXT_TOKENS", "32768")),
                stream=False,  # Don't stream for structured JSON output
            )
            self.llm = OpenAIBackend(config, api_key=resolved_api_key, api_key_env=api_key_env)

    def generate_blueprint(
        self,
        task_description: str,
        codebase_context: Optional[str] = None,
        existing_patterns: Optional[str] = None,
    ) -> Blueprint:
        """
        Generate architecture blueprint for a task.

        Args:
            task_description: User's task/feature request
            codebase_context: Optional context about existing codebase
            existing_patterns: Optional patterns/conventions to follow

        Returns:
            Blueprint object with complete architecture plan

        Raises:
            ClarityGeneratorError: If generation fails
        """
        logger.info(f"Generating blueprint for: {task_description}")

        # Build prompt
        user_prompt = generate_architecture_prompt(
            task_description=task_description,
            codebase_context=codebase_context or "",
            existing_patterns=existing_patterns or "",
        )

        # Call LLM
        try:
            messages = [
                {"role": "system", "content": ARCHITECTURE_GENERATION_SYSTEM_PROMPT},
                {"role": "user", "content": user_prompt},
            ]

            response = self.llm.generate(messages)
            content = response.content

            # Extract JSON from response (handle markdown code blocks)
            json_content = self._extract_json(content)

            # Parse into Blueprint
            blueprint = self._parse_blueprint(json_content)

            logger.info(
                f"Blueprint generated: {len(blueprint.components)} components, "
                f"{len(blueprint.design_decisions)} decisions"
            )

            return blueprint

        except Exception as e:
            logger.error(f"Failed to generate blueprint: {e}")
            raise ClarityGeneratorError(f"Blueprint generation failed: {e}")

    def refine_blueprint(
        self,
        current_blueprint: Blueprint,
        user_feedback: str,
    ) -> Blueprint:
        """
        Refine a blueprint based on user feedback.

        Args:
            current_blueprint: Current blueprint
            user_feedback: User's feedback/change requests

        Returns:
            Refined Blueprint object

        Raises:
            ClarityGeneratorError: If refinement fails
        """
        logger.info("Refining blueprint based on user feedback")

        # Convert current blueprint to JSON
        blueprint_json = json.dumps(current_blueprint.to_dict(), indent=2)

        # Build refinement prompt
        user_prompt = generate_refinement_prompt(blueprint_json, user_feedback)

        # Call LLM
        try:
            messages = [
                {"role": "system", "content": ARCHITECTURE_GENERATION_SYSTEM_PROMPT},
                {"role": "user", "content": user_prompt},
            ]

            response = self.llm.generate(messages)
            content = response.content

            # Extract and parse JSON
            json_content = self._extract_json(content)
            blueprint = self._parse_blueprint(json_content)

            logger.info("Blueprint refined successfully")
            return blueprint

        except Exception as e:
            logger.error(f"Failed to refine blueprint: {e}")
            raise ClarityGeneratorError(f"Blueprint refinement failed: {e}")

    def _extract_json(self, content: str) -> str:
        """
        Extract JSON from LLM response (handles markdown code blocks).

        Args:
            content: Raw LLM response

        Returns:
            Clean JSON string

        Raises:
            ValueError: If no valid JSON found
        """
        # Try to find JSON in markdown code block
        if "```json" in content:
            start = content.find("```json") + 7
            end = content.find("```", start)
            if end > start:
                return content[start:end].strip()

        # Try to find JSON in generic code block
        if "```" in content:
            start = content.find("```") + 3
            end = content.find("```", start)
            if end > start:
                json_candidate = content[start:end].strip()
                # Check if it starts with { (likely JSON)
                if json_candidate.startswith("{"):
                    return json_candidate

        # Try to find raw JSON (look for { at start)
        content = content.strip()
        if content.startswith("{"):
            return content

        raise ValueError("No valid JSON found in response")

    def _safe_parse_component_type(self, type_str: str) -> ComponentType:
        """
        Safely parse component type with fallback to MODULE for unknown types.

        Args:
            type_str: Component type string from LLM

        Returns:
            ComponentType enum value
        """
        try:
            return ComponentType(type_str)
        except ValueError:
            logger.warning(
                f"Unknown component type '{type_str}', falling back to MODULE. "
                f"Consider adding this type to ComponentType enum."
            )
            return ComponentType.MODULE

    def _safe_parse_relation_type(self, type_str: str) -> RelationType:
        """
        Safely parse relation type with fallback to USES for unknown types.

        Args:
            type_str: Relation type string from LLM

        Returns:
            RelationType enum value
        """
        try:
            return RelationType(type_str)
        except ValueError:
            logger.warning(
                f"Unknown relation type '{type_str}', falling back to USES. "
                f"Consider adding this type to RelationType enum."
            )
            return RelationType.USES

    def _parse_blueprint(self, json_str: str) -> Blueprint:
        """
        Parse JSON string into Blueprint object.

        Args:
            json_str: JSON string from LLM

        Returns:
            Blueprint object

        Raises:
            ValueError: If JSON is invalid or missing required fields
        """
        try:
            data = json.loads(json_str)
        except json.JSONDecodeError as e:
            raise ValueError(f"Invalid JSON: {e}")

        # Parse components
        components = []
        for comp_data in data.get("components", []):
            components.append(
                Component(
                    name=comp_data["name"],
                    type=self._safe_parse_component_type(comp_data["type"]),
                    purpose=comp_data["purpose"],
                    responsibilities=comp_data["responsibilities"],
                    file_path=comp_data["file_path"],
                    layer=comp_data.get("layer"),
                    key_methods=comp_data.get("key_methods", []),
                    dependencies=comp_data.get("dependencies", []),
                )
            )

        # Parse design decisions
        design_decisions = []
        for dd_data in data.get("design_decisions", []):
            design_decisions.append(
                DesignDecision(
                    decision=dd_data["decision"],
                    rationale=dd_data["rationale"],
                    alternatives_considered=dd_data.get("alternatives_considered", []),
                    trade_offs=dd_data.get("trade_offs"),
                    category=dd_data.get("category"),
                )
            )

        # Parse file actions
        file_actions = []
        for fa_data in data.get("file_actions", []):
            file_actions.append(
                FileAction(
                    file_path=fa_data["file_path"],
                    action=FileActionType(fa_data["action"]),
                    description=fa_data["description"],
                    estimated_lines=fa_data.get("estimated_lines"),
                    components_affected=fa_data.get("components_affected", []),
                )
            )

        # Parse relationships
        relationships = []
        for rel_data in data.get("relationships", []):
            relationships.append(
                Relationship(
                    source=rel_data["source"],
                    target=rel_data["target"],
                    type=self._safe_parse_relation_type(rel_data["type"]),
                    description=rel_data.get("description"),
                )
            )

        # Create blueprint
        blueprint = Blueprint(
            task_description=data.get("task_description", ""),
            components=components,
            design_decisions=design_decisions,
            file_actions=file_actions,
            relationships=relationships,
            estimated_complexity=data.get("estimated_complexity"),
            estimated_time=data.get("estimated_time"),
            prerequisites=data.get("prerequisites", []),
            risks=data.get("risks", []),
        )

        return blueprint
