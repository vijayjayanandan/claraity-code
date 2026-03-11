"""Model configurations and recommendations."""

from typing import Optional

from pydantic import BaseModel


class ModelConfig(BaseModel):
    """Configuration for a specific model."""

    name: str
    context_window: int
    recommended_temperature: float = 0.2
    recommended_top_p: float = 0.95
    recommended_top_k: int = 40
    supports_system_prompt: bool = True
    use_case: str = "general"
    description: str = ""


# Recommended models for coding tasks
CODING_MODELS = {
    "codellama:7b-instruct": ModelConfig(
        name="codellama:7b-instruct",
        context_window=4096,
        recommended_temperature=0.2,
        use_case="coding",
        description="Code Llama 7B optimized for instruction following. Good general coding model.",
    ),
    "codellama:13b-instruct": ModelConfig(
        name="codellama:13b-instruct",
        context_window=4096,
        recommended_temperature=0.2,
        use_case="coding",
        description="Code Llama 13B. Better quality than 7B but slower.",
    ),
    "deepseek-coder:6.7b-instruct": ModelConfig(
        name="deepseek-coder:6.7b-instruct",
        context_window=16384,
        recommended_temperature=0.2,
        use_case="coding",
        description="DeepSeek Coder 6.7B. Excellent coding capabilities with large context.",
    ),
    "qwen2.5-coder:7b": ModelConfig(
        name="qwen2.5-coder:7b",
        context_window=32768,
        recommended_temperature=0.2,
        use_case="coding",
        description="Qwen 2.5 Coder 7B. Very large context window, great for complex tasks.",
    ),
    "codestral:7b": ModelConfig(
        name="codestral:7b",
        context_window=8192,
        recommended_temperature=0.3,
        use_case="coding",
        description="Mistral's code model. Good reasoning and code generation.",
    ),
    "qwen3-coder:30b": ModelConfig(
        name="qwen3-coder:30b",
        context_window=262144,
        recommended_temperature=0.2,
        use_case="coding",
        description="Qwen3 Coder 30B. Massive 262K context window with enhanced agentic capabilities. Best for complex multi-file tasks.",
    ),
}

# General purpose models
GENERAL_MODELS = {
    "llama3.2:8b-instruct": ModelConfig(
        name="llama3.2:8b-instruct",
        context_window=8192,
        recommended_temperature=0.3,
        use_case="general",
        description="Llama 3.2 8B. Balanced performance for various tasks.",
    ),
    "mistral:7b-instruct": ModelConfig(
        name="mistral:7b-instruct",
        context_window=8192,
        recommended_temperature=0.3,
        use_case="general",
        description="Mistral 7B. Fast and capable general purpose model.",
    ),
    "phi3:medium": ModelConfig(
        name="phi3:medium",
        context_window=4096,
        recommended_temperature=0.3,
        use_case="general",
        description="Phi-3 Medium. Efficient for limited resources.",
    ),
}

# All available configurations
ALL_MODELS = {**CODING_MODELS, **GENERAL_MODELS}


def get_model_config(model_name: str) -> ModelConfig | None:
    """
    Get configuration for a model.

    Args:
        model_name: Name of the model

    Returns:
        Model configuration or None if not found
    """
    return ALL_MODELS.get(model_name)


def list_recommended_models(use_case: str = "coding") -> dict[str, ModelConfig]:
    """
    List recommended models for a use case.

    Args:
        use_case: Use case filter ('coding' or 'general')

    Returns:
        Dictionary of model configurations
    """
    if use_case == "coding":
        return CODING_MODELS
    elif use_case == "general":
        return GENERAL_MODELS
    else:
        return ALL_MODELS


def get_best_model_for_context(required_context: int) -> str | None:
    """
    Get best model name for required context window.

    Args:
        required_context: Required context window size

    Returns:
        Model name or None
    """
    suitable_models = [
        (name, config)
        for name, config in CODING_MODELS.items()
        if config.context_window >= required_context
    ]

    if not suitable_models:
        return None

    # Sort by context window (prefer larger) and return first
    suitable_models.sort(key=lambda x: x[1].context_window, reverse=True)
    return suitable_models[0][0]
