#!/usr/bin/env python3
"""Export ClarAIty database to JSON for visualization."""

import sqlite3
import json
from pathlib import Path

def export_to_json(db_path: str, output_path: str):
    """Export ClarAIty database to JSON format."""

    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row  # Enable column access by name
    cursor = conn.cursor()

    data = {
        "components": [],
        "relationships": [],
        "artifacts": [],
        "design_decisions": [],
        "metadata": {
            "project_name": None,
            "version": None,
            "description": None
        }
    }

    # Export components
    cursor.execute("""
        SELECT id, name, type, layer, status, purpose, business_value,
               design_rationale, responsibilities, created_at
        FROM components
        ORDER BY layer, name
    """)
    for row in cursor.fetchall():
        data["components"].append({
            "id": row["id"],
            "name": row["name"],
            "type": row["type"],
            "layer": row["layer"],
            "status": row["status"],
            "purpose": row["purpose"],
            "business_value": row["business_value"],
            "design_rationale": row["design_rationale"],
            "responsibilities": row["responsibilities"],
            "created_at": row["created_at"]
        })

    # Export relationships
    cursor.execute("""
        SELECT r.id, r.source_id, r.target_id, r.relationship_type,
               r.description, r.criticality,
               c1.name as source_name, c2.name as target_name
        FROM component_relationships r
        JOIN components c1 ON r.source_id = c1.id
        JOIN components c2 ON r.target_id = c2.id
        ORDER BY r.id
    """)
    for row in cursor.fetchall():
        data["relationships"].append({
            "id": row["id"],
            "source_id": row["source_id"],
            "target_id": row["target_id"],
            "source_name": row["source_name"],
            "target_name": row["target_name"],
            "type": row["relationship_type"],
            "description": row["description"],
            "criticality": row["criticality"]
        })

    # Export code artifacts (limited to save space)
    cursor.execute("""
        SELECT a.id, a.component_id, a.type, a.name,
               a.file_path, a.line_start, a.line_end,
               a.description, a.language,
               c.name as component_name
        FROM code_artifacts a
        JOIN components c ON a.component_id = c.id
        ORDER BY c.name, a.type, a.name
        LIMIT 1000
    """)
    for row in cursor.fetchall():
        data["artifacts"].append({
            "id": row["id"],
            "component_id": row["component_id"],
            "component_name": row["component_name"],
            "type": row["type"],
            "name": row["name"],
            "file_path": row["file_path"],
            "line_start": row["line_start"],
            "line_end": row["line_end"],
            "description": row["description"],
            "language": row["language"]
        })

    # Export design decisions
    cursor.execute("""
        SELECT d.id, d.component_id, d.decision_type, d.question,
               d.chosen_solution, d.rationale, d.alternatives_considered,
               d.trade_offs, d.decided_by, d.confidence,
               c.name as component_name
        FROM design_decisions d
        LEFT JOIN components c ON d.component_id = c.id
        ORDER BY d.created_at DESC
    """)
    for row in cursor.fetchall():
        data["design_decisions"].append({
            "id": row["id"],
            "component_id": row["component_id"],
            "component_name": row["component_name"],
            "type": row["decision_type"],
            "question": row["question"],
            "chosen_solution": row["chosen_solution"],
            "rationale": row["rationale"],
            "alternatives_considered": row["alternatives_considered"],
            "trade_offs": row["trade_offs"],
            "decided_by": row["decided_by"],
            "confidence": row["confidence"]
        })

    # Get project metadata from generation_sessions if available
    cursor.execute("SELECT project_name FROM generation_sessions LIMIT 1")
    row = cursor.fetchone()
    if row:
        data["metadata"]["project_name"] = row["project_name"]

    # Add statistics
    data["stats"] = {
        "total_components": len(data["components"]),
        "total_relationships": len(data["relationships"]),
        "total_artifacts": len(data["artifacts"]),
        "total_design_decisions": len(data["design_decisions"]),
        "components_by_type": {},
        "components_by_layer": {}
    }

    # Count components by type and layer
    for comp in data["components"]:
        comp_type = comp["type"]
        comp_layer = comp["layer"]
        data["stats"]["components_by_type"][comp_type] = \
            data["stats"]["components_by_type"].get(comp_type, 0) + 1
        data["stats"]["components_by_layer"][comp_layer] = \
            data["stats"]["components_by_layer"].get(comp_layer, 0) + 1

    conn.close()

    # Write to JSON file
    output_file = Path(output_path)
    output_file.parent.mkdir(parents=True, exist_ok=True)

    with open(output_file, 'w', encoding='utf-8') as f:
        json.dump(data, f, indent=2, ensure_ascii=False)

    print(f"✅ Exported ClarAIty data to {output_path}")
    print(f"📊 Statistics:")
    print(f"   - Components: {data['stats']['total_components']}")
    print(f"   - Relationships: {data['stats']['total_relationships']}")
    print(f"   - Artifacts: {data['stats']['total_artifacts']}")
    print(f"   - Design Decisions: {data['stats']['total_design_decisions']}")
    print(f"\n📦 Components by layer:")
    for layer, count in sorted(data['stats']['components_by_layer'].items()):
        print(f"   - {layer}: {count}")
    print(f"\n🔧 Components by type:")
    for comp_type, count in sorted(data['stats']['components_by_type'].items()):
        print(f"   - {comp_type}: {count}")

if __name__ == "__main__":
    db_path = ".clarity/ai-coding-agent.db"
    output_path = "clarity-data.json"
    export_to_json(db_path, output_path)
