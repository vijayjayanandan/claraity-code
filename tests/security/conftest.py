"""Security test fixtures."""
import os

os.environ["OBSERVABILITY_ENABLED"] = "false"

# Prime import chain to avoid circular imports
import src.core  # noqa: F401
