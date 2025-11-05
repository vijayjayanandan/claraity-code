"""
Sync Orchestrator for ClarAIty

Coordinates synchronization between filesystem and database.
Orchestrates: FileWatcher → ChangeDetector → Analyzer → Database → Events
"""

import asyncio
import logging
from dataclasses import dataclass, field
from typing import List, Dict, Any, Optional
from datetime import datetime, timedelta
from pathlib import Path

from .event_bus import event_bus, EventType, ClarityEvent, emit_sync_started, emit_sync_completed, emit_error
from .change_detector import ChangeDetector, ChangeImpact
from ..core.database import ClarityDB
from ..analyzer.code_analyzer import CodeAnalyzer

logger = logging.getLogger(__name__)


@dataclass
class SyncResult:
    """Result of a sync operation."""
    success: bool
    files_analyzed: int = 0
    components_updated: int = 0
    components_added: int = 0
    components_removed: int = 0
    artifacts_updated: int = 0
    relationships_updated: int = 0
    errors: List[str] = field(default_factory=list)
    duration_seconds: float = 0.0

    def to_dict(self) -> Dict[str, Any]:
        """Convert to dictionary."""
        return {
            'success': self.success,
            'files_analyzed': self.files_analyzed,
            'components_updated': self.components_updated,
            'components_added': self.components_added,
            'components_removed': self.components_removed,
            'artifacts_updated': self.artifacts_updated,
            'relationships_updated': self.relationships_updated,
            'error_count': len(self.errors),
            'errors': self.errors[:5],  # First 5 errors
            'duration_seconds': self.duration_seconds,
        }


class SyncOrchestrator:
    """
    Orchestrate synchronization between filesystem and ClarAIty database.

    Workflow:
    1. Listen to FILES_BATCH_CHANGED events
    2. Detect impact (which components affected)
    3. Re-analyze affected files
    4. Update database
    5. Emit completion events
    """

    def __init__(
        self,
        clarity_db: ClarityDB,
        working_directory: str,
        auto_sync: bool = True
    ):
        """
        Initialize sync orchestrator.

        Args:
            clarity_db: ClarityDB instance
            working_directory: Root directory of codebase
            auto_sync: Automatically sync on file changes (default: True)
        """
        self.db = clarity_db
        self.working_directory = Path(working_directory).resolve()
        self.auto_sync = auto_sync

        # Components
        self.change_detector = ChangeDetector(clarity_db)
        self.analyzer = CodeAnalyzer()

        # Sync state
        self._syncing = False
        self._sync_lock = asyncio.Lock()
        self._last_sync: Optional[datetime] = None
        self._sync_count = 0

        # Subscribe to file change events
        if auto_sync:
            event_bus.subscribe(EventType.FILES_BATCH_CHANGED, self._on_files_changed)
            logger.info("SyncOrchestrator subscribed to file change events")

        logger.info(f"SyncOrchestrator initialized (auto_sync={auto_sync})")

    async def _on_files_changed(self, event: ClarityEvent):
        """
        Handle file batch changed event.

        Args:
            event: ClarityEvent with file changes
        """
        data = event.data
        created = data.get('created', [])
        modified = data.get('modified', [])
        deleted = data.get('deleted', [])

        logger.info(f"Files changed event received: {len(created)}C, {len(modified)}M, {len(deleted)}D")

        # Trigger sync
        try:
            await self.sync_files(created, modified, deleted)
        except Exception as e:
            logger.error(f"Error during auto-sync: {e}", exc_info=True)
            await emit_error("sync_failed", str(e), source="sync_orchestrator")

    async def sync_files(
        self,
        created: List[str],
        modified: List[str],
        deleted: List[str]
    ) -> SyncResult:
        """
        Synchronize file changes to database.

        Args:
            created: List of created file paths
            modified: List of modified file paths
            deleted: List of deleted file paths

        Returns:
            SyncResult with statistics
        """
        # Prevent concurrent syncs
        if not await self._sync_lock.acquire():
            logger.warning("Sync already in progress, skipping")
            return SyncResult(success=False, errors=["Sync already in progress"])

        try:
            start_time = datetime.utcnow()
            self._syncing = True
            result = SyncResult(success=True)

            logger.info(f"Starting sync: {len(created)}C, {len(modified)}M, {len(deleted)}D")
            await emit_sync_started(
                scope="incremental",
                file_count=len(created) + len(modified) + len(deleted),
                source="sync_orchestrator"
            )

            # Step 1: Detect impact
            impact = await self.change_detector.analyze_changes(created, modified, deleted)
            logger.info(f"Impact analysis: {impact.summary()}")

            # Step 2: Handle deletions first
            if deleted:
                result.components_removed += await self._handle_deletions(impact)

            # Step 3: Handle new and modified files
            files_to_analyze = created + modified
            if files_to_analyze:
                analyze_result = await self._analyze_and_update(files_to_analyze, impact)
                result.files_analyzed = analyze_result['files_analyzed']
                result.components_added = analyze_result['components_added']
                result.components_updated = analyze_result['components_updated']
                result.artifacts_updated = analyze_result['artifacts_updated']

            # Step 4: Update relationships (if components changed)
            if impact.affected_component_ids:
                # Note: Full relationship inference is expensive
                # For now, we just mark them as potentially stale
                # Full re-inference can be done on-demand
                pass

            # Success
            end_time = datetime.utcnow()
            result.duration_seconds = (end_time - start_time).total_seconds()

            self._last_sync = end_time
            self._sync_count += 1

            logger.info(
                f"Sync completed successfully in {result.duration_seconds:.2f}s: "
                f"{result.files_analyzed} files, {result.components_added} new components, "
                f"{result.components_updated} updated"
            )

            await emit_sync_completed(result.to_dict(), source="sync_orchestrator")

            return result

        except Exception as e:
            logger.error(f"Sync failed: {e}", exc_info=True)
            result = SyncResult(success=False, errors=[str(e)])
            await emit_error("sync_failed", str(e), source="sync_orchestrator")
            return result

        finally:
            self._syncing = False
            self._sync_lock.release()

    async def _handle_deletions(self, impact: ChangeImpact) -> int:
        """
        Handle deleted files.

        Args:
            impact: ChangeImpact with deleted files

        Returns:
            Number of components removed
        """
        if not impact.deleted_files:
            return 0

        logger.info(f"Handling {len(impact.deleted_files)} deleted files")
        removed_count = 0

        for file_path in impact.deleted_files:
            try:
                # Find artifacts in this file
                artifacts = self.db.query_artifacts(filters={'file_path': file_path})

                # Delete artifacts and their components (if no other artifacts)
                for artifact in artifacts:
                    component_id = artifact.get('component_id')
                    artifact_id = artifact['id']

                    # Delete artifact
                    self.db.delete_artifact(artifact_id)

                    # Check if component has other artifacts
                    if component_id:
                        remaining = self.db.query_artifacts(filters={'component_id': component_id})
                        if not remaining:
                            # No more artifacts, delete component
                            self.db.delete_component(component_id)
                            removed_count += 1
                            logger.debug(f"Deleted component {component_id} (no remaining artifacts)")

            except Exception as e:
                logger.warning(f"Error handling deletion of {file_path}: {e}")

        logger.info(f"Removed {removed_count} components from deleted files")
        return removed_count

    async def _analyze_and_update(
        self,
        file_paths: List[str],
        impact: ChangeImpact
    ) -> Dict[str, int]:
        """
        Analyze files and update database.

        Args:
            file_paths: List of file paths to analyze
            impact: ChangeImpact with context

        Returns:
            Statistics dictionary
        """
        logger.info(f"Analyzing {len(file_paths)} files")

        stats = {
            'files_analyzed': 0,
            'components_added': 0,
            'components_updated': 0,
            'artifacts_updated': 0,
        }

        for file_path in file_paths:
            try:
                # Skip if file doesn't exist (edge case)
                if not Path(file_path).exists():
                    logger.warning(f"File does not exist, skipping: {file_path}")
                    continue

                # Analyze file
                components = self.analyzer.analyze_file(file_path)
                stats['files_analyzed'] += 1

                if not components:
                    logger.debug(f"No components found in {file_path}")
                    continue

                # Update database for each component
                for comp in components:
                    # Check if component already exists (by name + file_path)
                    existing = self.db.query_components(filters={
                        'name': comp['name'],
                        'file_path': file_path
                    })

                    if existing:
                        # Update existing component
                        component_id = existing[0]['id']
                        self.db.update_component(component_id, **comp)
                        stats['components_updated'] += 1
                        logger.debug(f"Updated component: {comp['name']}")
                    else:
                        # Add new component
                        component_id = self.db.add_component(comp)
                        stats['components_added'] += 1
                        logger.debug(f"Added new component: {comp['name']}")

            except Exception as e:
                logger.warning(f"Error analyzing {file_path}: {e}")

        logger.info(
            f"Analysis complete: {stats['files_analyzed']} files, "
            f"{stats['components_added']} new, {stats['components_updated']} updated"
        )

        return stats

    async def full_rescan(self, directory: Optional[str] = None) -> SyncResult:
        """
        Perform full rescan of codebase.

        This is expensive and should only be done:
        - On initial setup
        - After major refactoring
        - When sync gets out of sync

        Args:
            directory: Directory to scan (default: working_directory)

        Returns:
            SyncResult
        """
        scan_dir = Path(directory) if directory else self.working_directory

        logger.info(f"Starting full rescan of {scan_dir}")
        await emit_sync_started(scope="full", file_count=0, source="sync_orchestrator")

        start_time = datetime.utcnow()

        try:
            # Get all Python files
            python_files = list(scan_dir.rglob("*.py"))

            # Filter out ignored paths
            ignored_patterns = ["__pycache__", ".venv", "venv", ".git", "node_modules"]
            filtered_files = [
                str(f) for f in python_files
                if not any(pattern in str(f) for pattern in ignored_patterns)
            ]

            logger.info(f"Found {len(filtered_files)} Python files to analyze")

            # Clear database (optional - or keep existing and update)
            # self.db.clear_all()  # Uncomment if you want fresh start

            # Analyze all files
            result = await self._analyze_and_update(
                filtered_files,
                ChangeImpact()  # Empty impact for full scan
            )

            # Create result
            end_time = datetime.utcnow()
            sync_result = SyncResult(
                success=True,
                files_analyzed=result['files_analyzed'],
                components_added=result['components_added'],
                components_updated=result['components_updated'],
                duration_seconds=(end_time - start_time).total_seconds()
            )

            logger.info(
                f"Full rescan completed in {sync_result.duration_seconds:.2f}s: "
                f"{sync_result.files_analyzed} files, {sync_result.components_added} components"
            )

            await emit_sync_completed(sync_result.to_dict(), source="sync_orchestrator")

            return sync_result

        except Exception as e:
            logger.error(f"Full rescan failed: {e}", exc_info=True)
            await emit_error("full_rescan_failed", str(e), source="sync_orchestrator")
            return SyncResult(success=False, errors=[str(e)])

    def get_status(self) -> Dict[str, Any]:
        """Get current sync status."""
        return {
            'syncing': self._syncing,
            'auto_sync_enabled': self.auto_sync,
            'last_sync': self._last_sync.isoformat() if self._last_sync else None,
            'sync_count': self._sync_count,
            'working_directory': str(self.working_directory),
        }
