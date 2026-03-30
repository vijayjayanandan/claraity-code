"""
ClarAIty Schema Migration: Implementation Specs Enhancement

Adds 3 new tables to support LLM-native workflow with detailed implementation specs:
1. component_methods - Method signatures with parameters, returns, exceptions
2. component_acceptance_criteria - Definition of "done" (tests, coverage, integration)
3. component_patterns - Design patterns and antipatterns with code examples

Engineering Principles:
- Idempotent (safe to run multiple times)
- Backwards compatible (no breaking changes)
- Production-grade constraints and indexes
- Clear rollback path
"""

import sqlite3
import logging
from pathlib import Path
from datetime import datetime

logging.basicConfig(level=logging.INFO, format='[%(levelname)s] %(message)s')
logger = logging.getLogger(__name__)

DB_PATH = Path(".claraity/ai-coding-agent.db")


def verify_db_exists():
    """Verify database exists before migration."""
    if not DB_PATH.exists():
        raise FileNotFoundError(f"Database not found: {DB_PATH}")
    logger.info(f"[OK] Database found: {DB_PATH}")


def table_exists(cursor, table_name: str) -> bool:
    """Check if table exists."""
    cursor.execute(
        "SELECT name FROM sqlite_master WHERE type='table' AND name=?",
        (table_name,)
    )
    return cursor.fetchone() is not None


def create_component_methods_table(cursor):
    """Create component_methods table for method signatures."""

    if table_exists(cursor, "component_methods"):
        logger.info("[SKIP] component_methods table already exists")
        return

    logger.info("[CREATE] component_methods table")

    cursor.execute("""
        CREATE TABLE component_methods (
            id TEXT PRIMARY KEY,
            component_id TEXT NOT NULL,
            method_name TEXT NOT NULL,
            signature TEXT NOT NULL,
            return_type TEXT,
            description TEXT,
            parameters TEXT,              -- JSON array of parameter objects
            raises TEXT,                  -- JSON array of exception names
            example_usage TEXT,
            is_abstract BOOLEAN DEFAULT 1,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,

            FOREIGN KEY (component_id) REFERENCES components(id) ON DELETE CASCADE,
            UNIQUE(component_id, method_name)
        )
    """)

    # Create indexes for efficient queries
    cursor.execute("""
        CREATE INDEX idx_component_methods_component_id
        ON component_methods(component_id)
    """)

    cursor.execute("""
        CREATE INDEX idx_component_methods_method_name
        ON component_methods(method_name)
    """)

    logger.info("[OK] component_methods table created with 2 indexes")


def create_acceptance_criteria_table(cursor):
    """Create component_acceptance_criteria table for definition of done."""

    if table_exists(cursor, "component_acceptance_criteria"):
        logger.info("[SKIP] component_acceptance_criteria table already exists")
        return

    logger.info("[CREATE] component_acceptance_criteria table")

    cursor.execute("""
        CREATE TABLE component_acceptance_criteria (
            id TEXT PRIMARY KEY,
            component_id TEXT NOT NULL,
            criteria_type TEXT NOT NULL,    -- 'test_coverage', 'performance', 'integration', 'breaking_changes'
            description TEXT NOT NULL,
            target_value TEXT,              -- e.g., "90%", "< 100ms", "5 tests"
            validation_method TEXT,         -- How to check (e.g., "pytest --cov")
            priority TEXT DEFAULT 'required',  -- 'required', 'recommended', 'optional'
            status TEXT DEFAULT 'pending',  -- 'pending', 'in_progress', 'met', 'failed'
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,

            FOREIGN KEY (component_id) REFERENCES components(id) ON DELETE CASCADE,
            CHECK (priority IN ('required', 'recommended', 'optional')),
            CHECK (status IN ('pending', 'in_progress', 'met', 'failed'))
        )
    """)

    # Create indexes
    cursor.execute("""
        CREATE INDEX idx_acceptance_criteria_component_id
        ON component_acceptance_criteria(component_id)
    """)

    cursor.execute("""
        CREATE INDEX idx_acceptance_criteria_priority
        ON component_acceptance_criteria(priority)
    """)

    cursor.execute("""
        CREATE INDEX idx_acceptance_criteria_status
        ON component_acceptance_criteria(status)
    """)

    logger.info("[OK] component_acceptance_criteria table created with 3 indexes")


def create_patterns_table(cursor):
    """Create component_patterns table for implementation patterns."""

    if table_exists(cursor, "component_patterns"):
        logger.info("[SKIP] component_patterns table already exists")
        return

    logger.info("[CREATE] component_patterns table")

    cursor.execute("""
        CREATE TABLE component_patterns (
            id TEXT PRIMARY KEY,
            component_id TEXT NOT NULL,
            pattern_name TEXT NOT NULL,
            pattern_type TEXT NOT NULL,     -- 'design_pattern', 'error_handling', 'performance', 'security'
            description TEXT NOT NULL,
            code_example TEXT,
            antipatterns TEXT,              -- What NOT to do
            reference_links TEXT,           -- Links to docs/articles (renamed from 'references' - reserved keyword)
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,

            FOREIGN KEY (component_id) REFERENCES components(id) ON DELETE CASCADE,
            UNIQUE(component_id, pattern_name)
        )
    """)

    # Create indexes
    cursor.execute("""
        CREATE INDEX idx_component_patterns_component_id
        ON component_patterns(component_id)
    """)

    cursor.execute("""
        CREATE INDEX idx_component_patterns_type
        ON component_patterns(pattern_type)
    """)

    logger.info("[OK] component_patterns table created with 2 indexes")


def verify_migration(cursor):
    """Verify all tables and indexes were created successfully."""

    tables = ["component_methods", "component_acceptance_criteria", "component_patterns"]

    logger.info("\n[VERIFY] Migration verification")
    logger.info("=" * 80)

    all_good = True

    for table in tables:
        if table_exists(cursor, table):
            # Count rows
            cursor.execute(f"SELECT COUNT(*) FROM {table}")
            count = cursor.fetchone()[0]
            logger.info(f"[OK] {table:40} exists (rows: {count})")
        else:
            logger.error(f"[FAIL] {table:40} NOT FOUND")
            all_good = False

    # Verify foreign key constraints
    cursor.execute("PRAGMA foreign_keys")
    fk_enabled = cursor.fetchone()[0]
    if fk_enabled:
        logger.info(f"[OK] Foreign key constraints: enabled")
    else:
        logger.warning(f"[WARN] Foreign key constraints: disabled")

    logger.info("=" * 80)

    return all_good


def show_schema(cursor):
    """Display schema for new tables."""

    logger.info("\n[SCHEMA] New table structures")
    logger.info("=" * 80)

    for table in ["component_methods", "component_acceptance_criteria", "component_patterns"]:
        logger.info(f"\nTable: {table}")
        cursor.execute(f"PRAGMA table_info({table})")
        columns = cursor.fetchall()
        for col in columns:
            nullable = "NULL" if col[3] == 0 else "NOT NULL"
            default = f"DEFAULT={col[4]}" if col[4] else ""
            logger.info(f"  {col[1]:30} {col[2]:15} {nullable:10} {default}")

    logger.info("=" * 80)


def main():
    """Execute migration."""

    logger.info("\n" + "=" * 80)
    logger.info("ClarAIty Schema Migration: Implementation Specs Enhancement")
    logger.info("=" * 80)

    # Verify database exists
    verify_db_exists()

    # Connect and enable foreign keys
    conn = sqlite3.connect(DB_PATH)
    conn.execute("PRAGMA foreign_keys = ON")
    cursor = conn.cursor()

    try:
        # Create tables
        logger.info("\n[PHASE 1] Creating tables")
        logger.info("-" * 80)
        create_component_methods_table(cursor)
        create_acceptance_criteria_table(cursor)
        create_patterns_table(cursor)

        # Commit changes
        conn.commit()
        logger.info("\n[COMMIT] All changes committed to database")

        # Verify migration
        if verify_migration(cursor):
            logger.info("\n[SUCCESS] Migration completed successfully")
        else:
            logger.error("\n[FAIL] Migration verification failed")
            return 1

        # Show schema
        show_schema(cursor)

        logger.info("\n[NEXT STEP] Populate tables with implementation specs")
        logger.info("Run: python scripts/populate_implementation_specs.py")

        return 0

    except Exception as e:
        logger.error(f"\n[ERROR] Migration failed: {e}")
        conn.rollback()
        logger.info("[ROLLBACK] Changes rolled back")
        raise

    finally:
        conn.close()


if __name__ == "__main__":
    exit(main())
