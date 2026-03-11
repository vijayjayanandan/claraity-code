"""
AI Coding Agent - SQLite patch for ChromaDB compatibility.
"""

# Patch for ChromaDB to use pysqlite3-binary instead of system sqlite3
import sys

try:
    __import__("pysqlite3")
    sys.modules["sqlite3"] = sys.modules.pop("pysqlite3")
except ImportError:
    pass  # pysqlite3-binary not installed, use system sqlite3
