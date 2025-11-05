"""
Change Detector for ClarAIty

Analyzes file changes and determines impact on architecture.
Identifies affected components, relationships, and artifacts.
"""

import logging
from dataclasses import dataclass, field
from typing import List, Set, Dict, Any, Optional
from pathlib import Path

logger = logging.getLogger(__name__)


@dataclass
class ChangeImpact:
    """
    Represents the impact of file changes on the architecture.

    Identifies what needs to be updated in the database.
    """
    # Files that changed
    changed_files: List[str] = field(default_factory=list)

    # Components affected (need re-analysis)
    affected_component_ids: Set[int] = field(default_factory=set)
    affected_component_names: Set[str] = field(default_factory=set)

    # Artifacts that may have changed
    affected_artifact_ids: Set[int] = field(default_factory=set)

    # Relationships that may need updating
    affected_relationships: Set[tuple] = field(default_factory=set)  # (source_id, target_id)

    # New files (need full analysis)
    new_files: List[str] = field(default_factory=list)

    # Deleted files (need cleanup)
    deleted_files: List[str] = field(default_factory=list)

    # Modified files (need re-analysis)
    modified_files: List[str] = field(default_factory=list)

    def is_empty(self) -> bool:
        """Check if there's any impact."""
        return (
            not self.changed_files
            and not self.affected_component_ids
            and not self.new_files
            and not self.deleted_files
            and not self.modified_files
        )

    def summary(self) -> str:
        """Generate summary string."""
        return (
            f"ChangeImpact("
            f"changed={len(self.changed_files)}, "
            f"components={len(self.affected_component_ids)}, "
            f"new={len(self.new_files)}, "
            f"modified={len(self.modified_files)}, "
            f"deleted={len(self.deleted_files)})"
        )


class ChangeDetector:
    """
    Detect and analyze the impact of file changes.

    Queries database to find affected components and relationships.
    """

    def __init__(self, clarity_db):
        """
        Initialize change detector.

        Args:
            clarity_db: ClarityDB instance for querying existing data
        """
        self.db = clarity_db
        logger.info("ChangeDetector initialized")

    async def analyze_changes(
        self,
        created: List[str],
        modified: List[str],
        deleted: List[str]
    ) -> ChangeImpact:
        """
        Analyze file changes and determine impact.

        Args:
            created: List of created file paths
            modified: List of modified file paths
            deleted: List of deleted file paths

        Returns:
            ChangeImpact object describing what needs updating
        """
        impact = ChangeImpact(
            new_files=created,
            modified_files=modified,
            deleted_files=deleted,
            changed_files=created + modified + deleted
        )

        logger.info(
            f"Analyzing changes: {len(created)} created, "
            f"{len(modified)} modified, {len(deleted)} deleted"
        )

        # Analyze each type of change
        await self._analyze_created_files(created, impact)
        await self._analyze_modified_files(modified, impact)
        await self._analyze_deleted_files(deleted, impact)

        logger.info(f"Change analysis complete: {impact.summary()}")
        return impact

    async def _analyze_created_files(self, files: List[str], impact: ChangeImpact):
        """
        Analyze newly created files.

        New files need full analysis to extract components/artifacts.

        Args:
            files: List of created file paths
            impact: ChangeImpact to update
        """
        if not files:
            return

        logger.debug(f"Analyzing {len(files)} created files")

        # New files don't have existing components
        # They'll be fully analyzed by the analyzer
        # No database queries needed

    async def _analyze_modified_files(self, files: List[str], impact: ChangeImpact):
        """
        Analyze modified files.

        Need to find existing components/artifacts in these files.

        Args:
            files: List of modified file paths
            impact: ChangeImpact to update
        """
        if not files:
            return

        logger.debug(f"Analyzing {len(files)} modified files")

        # Query database for each file to find affected components
        for file_path in files:
            # Normalize path
            file_path = str(Path(file_path).resolve())

            # Find components in this file
            try:
                # Query artifacts to find components
                artifacts = self.db.query_artifacts(filters={'file_path': file_path})

                for artifact in artifacts:
                    component_id = artifact.get('component_id')
                    if component_id:
                        impact.affected_component_ids.add(component_id)
                        impact.affected_artifact_ids.add(artifact['id'])

                        # Get component details
                        component = self.db.get_component(component_id)
                        if component:
                            impact.affected_component_names.add(component['name'])

                logger.debug(
                    f"File {Path(file_path).name}: "
                    f"found {len(artifacts)} artifacts, "
                    f"{len(impact.affected_component_ids)} components"
                )

            except Exception as e:
                logger.warning(f"Error analyzing file {file_path}: {e}")

    async def _analyze_deleted_files(self, files: List[str], impact: ChangeImpact):
        """
        Analyze deleted files.

        Need to find and remove components/artifacts from deleted files.

        Args:
            files: List of deleted file paths
            impact: ChangeImpact to update
        """
        if not files:
            return

        logger.debug(f"Analyzing {len(files)} deleted files")

        # Query database for each file
        for file_path in files:
            # Normalize path
            file_path = str(Path(file_path).resolve())

            try:
                # Find artifacts to delete
                artifacts = self.db.query_artifacts(filters={'file_path': file_path})

                for artifact in artifacts:
                    component_id = artifact.get('component_id')
                    if component_id:
                        impact.affected_component_ids.add(component_id)
                        impact.affected_artifact_ids.add(artifact['id'])

                        # Get component details
                        component = self.db.get_component(component_id)
                        if component:
                            impact.affected_component_names.add(component['name'])

                logger.debug(
                    f"Deleted file {Path(file_path).name}: "
                    f"found {len(artifacts)} artifacts to remove"
                )

            except Exception as e:
                logger.warning(f"Error analyzing deleted file {file_path}: {e}")

    def detect_affected_relationships(self, impact: ChangeImpact) -> Set[tuple]:
        """
        Detect relationships affected by component changes.

        When components change, their relationships may need updating.

        Args:
            impact: ChangeImpact with affected components

        Returns:
            Set of (source_id, target_id) tuples needing review
        """
        if not impact.affected_component_ids:
            return set()

        logger.debug(f"Detecting affected relationships for {len(impact.affected_component_ids)} components")

        affected_rels = set()

        try:
            # Find relationships involving affected components
            all_relationships = self.db.get_all_relationships()

            for rel in all_relationships:
                source_id = rel.get('source_id')
                target_id = rel.get('target_id')

                # If either source or target is affected, relationship needs review
                if source_id in impact.affected_component_ids or target_id in impact.affected_component_ids:
                    affected_rels.add((source_id, target_id))

            logger.debug(f"Found {len(affected_rels)} affected relationships")

        except Exception as e:
            logger.warning(f"Error detecting affected relationships: {e}")

        return affected_rels
