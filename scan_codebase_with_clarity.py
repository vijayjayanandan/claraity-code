"""
Scan and Document AI Coding Agent Codebase with ClarAIty

This script uses ClarAIty's Document Existing mode to:
1. Scan the entire codebase
2. Extract components, artifacts, relationships
3. Store in ClarAIty database
4. Display statistics
"""

import sys
import asyncio
from pathlib import Path

# Fix Windows console encoding
if sys.platform == 'win32':
    import io
    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8')
    sys.stderr = io.TextIOWrapper(sys.stderr.buffer, encoding='utf-8')

# Add src to path
sys.path.insert(0, str(Path(__file__).parent))


async def main():
    """Run full codebase scan."""
    print("="*80)
    print("📊 ClarAIty: Document Existing Codebase")
    print("="*80)
    print()

    # Initialize components
    print("Step 1: Initializing ClarAIty components...")

    from src.clarity.core.database import ClarityDB
    from src.clarity.sync.orchestrator import SyncOrchestrator
    from src.clarity.config import get_config

    config = get_config()

    # Initialize database
    db_path = Path(config.db_path)
    db_path.parent.mkdir(parents=True, exist_ok=True)

    clarity_db = ClarityDB(str(db_path))
    print(f"✅ Database: {db_path}")
    print()

    # Get current statistics
    print("Current Database Statistics:")
    stats = clarity_db.get_statistics()
    print(f"  Components: {stats.get('total_components', 0)}")
    print(f"  Artifacts: {stats.get('total_artifacts', 0)}")
    print(f"  Relationships: {stats.get('total_relationships', 0)}")
    print()

    # Initialize sync orchestrator
    print("Step 2: Starting full codebase scan...")
    print("This will analyze all Python files in the project.")
    print()

    orchestrator = SyncOrchestrator(
        clarity_db=clarity_db,
        working_directory=str(Path.cwd()),
        auto_sync=False
    )

    # Run full rescan
    print("⏳ Scanning codebase...")
    result = await orchestrator.full_rescan()

    print()
    print("="*80)
    print("✅ Scan Complete!")
    print("="*80)
    print()

    # Show results
    print("Scan Results:")
    print(f"  Files Analyzed: {result.files_analyzed}")
    print(f"  Components Added: {result.components_added}")
    print(f"  Components Updated: {result.components_updated}")
    print(f"  Artifacts Updated: {result.artifacts_updated}")
    print(f"  Relationships Updated: {result.relationships_updated}")
    print(f"  Duration: {result.duration_seconds:.2f} seconds")
    print()

    if result.errors:
        print(f"⚠️  Errors: {len(result.errors)}")
        for error in result.errors[:5]:  # Show first 5 errors
            print(f"  - {error}")
        if len(result.errors) > 5:
            print(f"  ... and {len(result.errors) - 5} more")
        print()

    # Get updated statistics
    print("Updated Database Statistics:")
    stats = clarity_db.get_statistics()
    print(f"  Total Components: {stats.get('total_components', 0)}")
    print(f"  Total Artifacts: {stats.get('total_artifacts', 0)}")
    print(f"  Total Relationships: {stats.get('total_relationships', 0)}")
    print(f"  Total Flows: {stats.get('total_flows', 0)}")
    print(f"  Total Design Decisions: {stats.get('total_design_decisions', 0)}")
    print()

    # Show components by layer
    print("Components by Layer:")
    components = clarity_db.get_all_components()

    by_layer = {}
    for comp in components:
        layer = comp.get('layer', 'unknown')
        if layer not in by_layer:
            by_layer[layer] = []
        by_layer[layer].append(comp)

    for layer, comps in sorted(by_layer.items()):
        print(f"\n  {layer}: {len(comps)} components")
        for comp in comps[:5]:  # Show first 5
            print(f"    • {comp['name']} ({comp['type']})")
        if len(comps) > 5:
            print(f"    ... and {len(comps) - 5} more")

    print()
    print("="*80)
    print("📚 Codebase Documentation Complete!")
    print("="*80)
    print()
    print("Next steps:")
    print("  • View components: Use CLI 'clarity-components' command")
    print("  • Launch UI: python -m src.cli (then type 'clarity-ui')")
    print("  • Query database: Use ClarityDB API")
    print()


if __name__ == "__main__":
    asyncio.run(main())
