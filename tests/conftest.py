"""
Pytest configuration for all tests.

This file is automatically loaded by pytest before running any tests.
"""

import os

# Disable observability in all tests to prevent OTEL connection errors
# This must be set before any imports that trigger observability initialization
os.environ["OBSERVABILITY_ENABLED"] = "false"
