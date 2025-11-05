"""
Populate ClarAIty Database from Existing Codebase

Analyzes the existing AI coding agent codebase and populates
the ClarAIty database with components, artifacts, relationships,
and design decisions.

This demonstrates ClarAIty's "document mode" - using it to bring
clarity to existing code rather than generating new code.
"""

import sys

# Fix Windows console encoding for emojis
if sys.platform == 'win32':
    import io
    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8')
    sys.stderr = io.TextIOWrapper(sys.stderr.buffer, encoding='utf-8')
from pathlib import Path

# Add parent directory to path
sys.path.insert(0, str(Path(__file__).parent.parent.parent))

from src.clarity.core.database import ClarityDB
from src.clarity.analyzer.code_analyzer import CodeAnalyzer
from src.clarity.analyzer.design_decision_extractor import DesignDecisionExtractor


def populate_claraity_from_codebase(
    source_dir: str = "src",
    docs_file: str = "CODEBASE_CONTEXT.md",
    db_path: str = ".clarity/ai-coding-agent.db"
):
    """
    Populate ClarAIty database from existing codebase

    Args:
        source_dir: Source code directory to analyze
        docs_file: Documentation file with design decisions
        db_path: Path to ClarAIty database

    Returns:
        Summary dict
    """
    print("=" * 70)
    print("🎯 ClarAIty - Bringing Clarity to AI Coding Agent")
    print("=" * 70)
    print()

    # Initialize database
    print("📊 Initializing ClarAIty database...")
    db = ClarityDB(db_path)
    print(f"✓ Database created: {db_path}")
    print()

    # Create session
    print("🔄 Creating documentation session...")
    session_id = db.create_session(
        project_name="AI Coding Agent",
        session_type="documentation",
        mode="document",
        metadata={
            "purpose": "Document existing architecture",
            "source": "code_analysis",
            "version": "1.0"
        }
    )
    print(f"✓ Session created: {session_id[:8]}...")
    print()

    # Analyze code
    print("🔍 Analyzing codebase...")
    analyzer = CodeAnalyzer(source_dir=source_dir)
    components, artifacts, relationships = analyzer.analyze()

    analysis_summary = analyzer.get_summary()
    print(f"✓ Found {analysis_summary['total_components']} components")
    print(f"✓ Found {analysis_summary['total_artifacts']} artifacts")
    print(f"✓ Found {analysis_summary['total_relationships']} relationships")
    print()

    print("   Components by layer:")
    for layer, count in sorted(analysis_summary['components_by_layer'].items()):
        print(f"     - {layer}: {count}")
    print()

    # Populate components
    print("📝 Populating components...")
    for component in components.values():
        db.add_component(
            component_id=component.id,
            name=component.name,
            type_=component.type,
            layer=component.layer,
            purpose=component.purpose,
            business_value=component.business_value,
            design_rationale=component.design_rationale,
            responsibilities=component.responsibilities,
            status="completed"  # Existing code is already completed
        )
    print(f"✓ Populated {len(components)} components")
    print()

    # Populate artifacts
    print("📦 Populating artifacts...")
    artifact_count = 0
    for artifact in artifacts:
        if artifact.component_id and artifact.component_id in components:
            db.add_artifact(
                component_id=artifact.component_id,
                type_=artifact.type,
                name=artifact.name,
                file_path=artifact.file_path,
                line_start=artifact.line_start,
                line_end=artifact.line_end,
                description=artifact.description,
                language="python"
            )
            artifact_count += 1
    print(f"✓ Populated {artifact_count} artifacts")
    print()

    # Populate relationships
    print("🔗 Populating relationships...")
    relationship_count = 0
    for relationship in relationships:
        # Only add relationships where both components exist
        if (relationship.source_id in components and
            relationship.target_id in components):
            db.add_component_relationship(
                source_id=relationship.source_id,
                target_id=relationship.target_id,
                relationship_type=relationship.relationship_type,
                description=relationship.description,
                criticality="medium"
            )
            relationship_count += 1
    print(f"✓ Populated {relationship_count} relationships")
    print()

    # Extract design decisions
    print("💡 Extracting design decisions...")
    decision_extractor = DesignDecisionExtractor(docs_path=docs_file)
    decisions = decision_extractor.extract()

    decision_summary = decision_extractor.get_summary()
    print(f"✓ Found {decision_summary['total_decisions']} design decisions")
    print()

    # Populate design decisions
    print("📋 Populating design decisions...")
    decision_count = 0
    for decision in decisions:
        # Only add if component exists
        if decision.component_id in components:
            db.add_decision(
                component_id=decision.component_id,
                decision_type=decision.decision_type,
                question=decision.question,
                chosen_solution=decision.chosen_solution,
                rationale=decision.rationale,
                alternatives_considered=decision.alternatives_considered,
                trade_offs=decision.trade_offs,
                decided_by="Human",
                confidence=1.0
            )
            decision_count += 1
    print(f"✓ Populated {decision_count} design decisions")
    print()

    # Complete session
    db.complete_session(session_id, status="completed")

    # Get final statistics
    print("=" * 70)
    print("📊 Final Statistics")
    print("=" * 70)
    stats = db.get_statistics()
    print(f"Components:     {stats['total_components']}")
    print(f"Artifacts:      {stats['total_artifacts']}")
    print(f"Relationships:  {stats['total_relationships']}")
    print(f"Decisions:      {stats['total_decisions']}")
    print(f"Sessions:       {stats['total_sessions']}")
    print()

    # Show architecture summary
    arch_summary = db.get_architecture_summary()
    print("Architecture by Layer:")
    for layer_info in arch_summary['layers']:
        print(f"  {layer_info['layer']:12} - {layer_info['component_count']:2} components "
              f"({layer_info['completed_count']} completed)")
    print()

    # Show some example components
    print("Example Components:")
    all_components = db.get_all_components()
    for comp in all_components[:5]:  # First 5
        print(f"  • {comp['name']:25} ({comp['layer']:10}) - {comp['purpose'][:50]}...")
    print()

    print("=" * 70)
    print("✅ ClarAIty population complete!")
    print("=" * 70)
    print()
    print(f"Database: {db_path}")
    print("You can now query the database to explore the architecture.")
    print()

    db.close()

    return {
        'session_id': session_id,
        'statistics': stats,
        'architecture_summary': arch_summary
    }


def query_architecture(db_path: str = ".clarity/ai-coding-agent.db"):
    """
    Query and display architecture information

    Args:
        db_path: Path to ClarAIty database
    """
    db = ClarityDB(db_path)

    print("\n" + "=" * 70)
    print("🔍 Architecture Query Examples")
    print("=" * 70)
    print()

    # Example 1: Get a specific component
    print("1. CodingAgent Component:")
    print("   " + "-" * 65)
    agent_component = db.get_component_details_full("CODINGAGENT")
    if agent_component:
        print(f"   Name: {agent_component['name']}")
        print(f"   Type: {agent_component['type']}")
        print(f"   Layer: {agent_component['layer']}")
        print(f"   Purpose: {agent_component['purpose']}")
        print(f"   Artifacts: {len(agent_component['artifacts'])}")
        print(f"   Decisions: {len(agent_component['decisions'])}")
        print(f"   Relationships: {len(agent_component['relationships']['outgoing'])} outgoing, "
              f"{len(agent_component['relationships']['incoming'])} incoming")
    print()

    # Example 2: Search components
    print("2. Search for 'memory' components:")
    print("   " + "-" * 65)
    memory_components = db.search_components("memory")
    for comp in memory_components[:3]:
        print(f"   • {comp['name']} - {comp['purpose'][:50]}...")
    print()

    # Example 3: Get all relationships
    print("3. Component Relationships:")
    print("   " + "-" * 65)
    relationships = db.get_all_relationships()
    for rel in relationships[:5]:
        print(f"   {rel['source_name']:20} --[{rel['relationship_type']}]--> {rel['target_name']}")
    print()

    db.close()


if __name__ == "__main__":
    import argparse

    parser = argparse.ArgumentParser(description="Populate ClarAIty from existing codebase")
    parser.add_argument("--source", default="src", help="Source directory to analyze")
    parser.add_argument("--docs", default="CODEBASE_CONTEXT.md", help="Documentation file")
    parser.add_argument("--db", default=".clarity/ai-coding-agent.db", help="Database path")
    parser.add_argument("--query", action="store_true", help="Query architecture after population")

    args = parser.parse_args()

    # Populate database
    result = populate_claraity_from_codebase(
        source_dir=args.source,
        docs_file=args.docs,
        db_path=args.db
    )

    # Query if requested
    if args.query:
        query_architecture(db_path=args.db)
