"""
ClarAIty Database Setup Tool

Allows the agent to initialize/scan ClarAIty DB for new projects.

Use cases:
1. User's first time using agent on existing project
2. ClarAIty DB doesn't exist or is empty
3. Need to rescan codebase after major changes
"""

import asyncio
from pathlib import Path
from typing import Dict, Any
from .base import Tool, ToolResult, ToolStatus


class ClaritySetupTool(Tool):
    """Tool for setting up/scanning ClarAIty database."""

    def __init__(self):
        super().__init__(
            name="clarity_setup",
            description="Initialize ClarAIty database by scanning the current project codebase. Use when ClarAIty DB doesn't exist or needs updating. Analyzes Python files to extract components, relationships, and architecture."
        )

    def execute(self, rescan: bool = False, **kwargs: Any) -> ToolResult:
        """
        Setup/scan ClarAIty database.

        Args:
            rescan: If True, force full rescan even if DB exists

        Returns:
            ToolResult with scan statistics
        """
        try:
            # Import here to avoid circular dependencies
            from src.clarity.core.database.clarity_db import ClarityDB
            from src.clarity.sync.orchestrator import SyncOrchestrator
            from src.clarity.config import get_config

            config = get_config()
            db_path = Path(config.db_path)

            # Check if DB exists
            db_exists = db_path.exists()

            if db_exists and not rescan:
                # DB already exists, just return stats
                db = ClarityDB(str(db_path))
                stats = db.get_statistics()
                db.close()

                output = []
                output.append("[INFO] ClarAIty database already exists")
                output.append(f"Database: {db_path}")
                output.append(f"\nCurrent Statistics:")
                output.append(f"  Components: {stats['total_components']}")
                output.append(f"  Artifacts: {stats['total_artifacts']}")
                output.append(f"  Relationships: {stats['total_relationships']}")
                output.append(f"  Decisions: {stats['total_decisions']}")
                output.append(f"\nUse rescan=true to force full rescan")

                return ToolResult(
                    tool_name=self.name,
                    status=ToolStatus.SUCCESS,
                    output="\n".join(output),
                    metadata={"db_exists": True, "stats": stats}
                )

            # Need to scan/setup
            output = []
            if rescan:
                output.append("[INFO] Rescanning ClarAIty database...")
            else:
                output.append("[INFO] Initializing ClarAIty database...")

            # Create DB directory
            db_path.parent.mkdir(parents=True, exist_ok=True)

            # Initialize database
            clarity_db = ClarityDB(str(db_path))
            output.append(f"[OK] Database initialized: {db_path}")

            # Get initial stats
            initial_stats = clarity_db.get_statistics()

            # Initialize sync orchestrator
            output.append(f"\n[INFO] Starting codebase scan...")
            output.append(f"[INFO] This may take 10-30 seconds for large projects...")

            orchestrator = SyncOrchestrator(
                clarity_db=clarity_db,
                working_directory=str(Path.cwd()),
                auto_sync=False
            )

            # Run full rescan (async operation, need to run in event loop)
            try:
                loop = asyncio.get_event_loop()
            except RuntimeError:
                loop = asyncio.new_event_loop()
                asyncio.set_event_loop(loop)

            result = loop.run_until_complete(orchestrator.full_rescan())

            # Format results
            output.append(f"\n[OK] Scan complete!")
            output.append(f"\nScan Results:")
            output.append(f"  Files Analyzed: {result.files_analyzed}")
            output.append(f"  Components Added: {result.components_added}")
            output.append(f"  Components Updated: {result.components_updated}")
            output.append(f"  Artifacts Updated: {result.artifacts_updated}")
            output.append(f"  Relationships Updated: {result.relationships_updated}")
            output.append(f"  Duration: {result.duration_seconds:.1f}s")

            if result.errors:
                output.append(f"\n[WARN] Errors: {len(result.errors)}")
                for error in result.errors[:3]:
                    output.append(f"  - {error}")
                if len(result.errors) > 3:
                    output.append(f"  ... and {len(result.errors) - 3} more")

            # Get final stats
            final_stats = clarity_db.get_statistics()
            output.append(f"\n[INFO] Database Statistics:")
            output.append(f"  Total Components: {final_stats['total_components']}")
            output.append(f"  Total Artifacts: {final_stats['total_artifacts']}")
            output.append(f"  Total Relationships: {final_stats['total_relationships']}")

            clarity_db.close()

            return ToolResult(
                tool_name=self.name,
                status=ToolStatus.SUCCESS,
                output="\n".join(output),
                metadata={
                    "db_exists": True,
                    "scan_result": {
                        "files_analyzed": result.files_analyzed,
                        "components_added": result.components_added,
                        "duration_seconds": result.duration_seconds
                    },
                    "stats": final_stats
                }
            )

        except ImportError as e:
            return ToolResult(
                tool_name=self.name,
                status=ToolStatus.ERROR,
                output=None,
                error=f"ClarAIty dependencies not available: {str(e)}"
            )
        except Exception as e:
            return ToolResult(
                tool_name=self.name,
                status=ToolStatus.ERROR,
                output=None,
                error=f"Failed to setup ClarAIty database: {str(e)}"
            )

    def _get_parameters(self) -> Dict[str, Any]:
        return {
            "type": "object",
            "properties": {
                "rescan": {
                    "type": "boolean",
                    "description": "If true, force full rescan even if database exists. Use when codebase has changed significantly."
                }
            },
            "required": []
        }


# Export
__all__ = ["ClaritySetupTool"]
