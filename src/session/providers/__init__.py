"""Provider translators for converting API responses to unified Message format.

Translators:
- openai: OpenAI API response → Message (primary)
- anthropic: Anthropic API response → Message (future)

Each translator provides:
- from_<provider>(): Convert API response to Message
- to_<provider>(): Convert Messages to API request format
"""

from .anthropic import from_anthropic, to_anthropic
from .openai import from_openai, to_openai

__all__ = [
    "from_openai",
    "to_openai",
    "from_anthropic",
    "to_anthropic",
]
