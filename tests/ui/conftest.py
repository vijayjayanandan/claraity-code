# Prime the import chain to avoid circular import errors.
# src.core loads the full chain (src.llm -> src.session -> src.core.events)
# in the correct order. See memory/circular-imports.md for details.
import src.core  # noqa: F401
