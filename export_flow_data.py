#!/usr/bin/env python3
"""Export ClarAIty execution flow data to JSON for visualization."""

import sqlite3
import json
from pathlib import Path

def export_flows_to_json(db_path: str, output_path: str):
    """Export execution flows with hierarchical steps to JSON."""

    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    cursor = conn.cursor()

    data = {
        "flows": [],
        "metadata": {
            "project_name": "AI Coding Agent",
            "description": "Execution flows showing how code flows through components"
        }
    }

    # Export flows
    cursor.execute("""
        SELECT id, name, description, trigger, flow_type, complexity, is_primary,
               created_at
        FROM execution_flows
        ORDER BY is_primary DESC, name
    """)

    for flow_row in cursor.fetchall():
        flow = {
            "id": flow_row["id"],
            "name": flow_row["name"],
            "description": flow_row["description"],
            "trigger": flow_row["trigger"],
            "flow_type": flow_row["flow_type"],
            "complexity": flow_row["complexity"],
            "is_primary": bool(flow_row["is_primary"]),
            "created_at": flow_row["created_at"],
            "steps": []
        }

        # Get all steps for this flow
        cursor.execute("""
            SELECT fs.id, fs.parent_step_id, fs.sequence, fs.level, fs.step_type,
                   fs.title, fs.description, fs.component_id,
                   fs.file_path, fs.line_start, fs.line_end, fs.function_name,
                   fs.decision_question, fs.decision_logic, fs.branches,
                   fs.is_critical, fs.notes,
                   c.name as component_name, c.layer as component_layer
            FROM flow_steps fs
            LEFT JOIN components c ON fs.component_id = c.id
            WHERE fs.flow_id = ?
            ORDER BY fs.level, fs.sequence
        """, (flow_row["id"],))

        all_steps = []
        for step_row in cursor.fetchall():
            step = {
                "id": step_row["id"],
                "parent_step_id": step_row["parent_step_id"],
                "sequence": step_row["sequence"],
                "level": step_row["level"],
                "step_type": step_row["step_type"],
                "title": step_row["title"],
                "description": step_row["description"],
                "component_id": step_row["component_id"],
                "component_name": step_row["component_name"],
                "component_layer": step_row["component_layer"],
                "file_path": step_row["file_path"],
                "line_start": step_row["line_start"],
                "line_end": step_row["line_end"],
                "function_name": step_row["function_name"],
                "decision_question": step_row["decision_question"],
                "decision_logic": step_row["decision_logic"],
                "branches": json.loads(step_row["branches"]) if step_row["branches"] else None,
                "is_critical": bool(step_row["is_critical"]),
                "notes": step_row["notes"],
                "substeps": []
            }
            all_steps.append(step)

        # Build hierarchical structure
        steps_by_id = {step["id"]: step for step in all_steps}

        # Organize into hierarchy
        for step in all_steps:
            if step["parent_step_id"]:
                parent = steps_by_id.get(step["parent_step_id"])
                if parent:
                    parent["substeps"].append(step)
            else:
                flow["steps"].append(step)

        data["flows"].append(flow)

    # Add statistics
    data["stats"] = {
        "total_flows": len(data["flows"]),
        "total_steps": sum(len(flow["steps"]) for flow in data["flows"]),
        "primary_flows": sum(1 for flow in data["flows"] if flow["is_primary"]),
        "flows_by_type": {},
        "flows_by_complexity": {}
    }

    for flow in data["flows"]:
        flow_type = flow["flow_type"]
        complexity = flow["complexity"]
        data["stats"]["flows_by_type"][flow_type] = \
            data["stats"]["flows_by_type"].get(flow_type, 0) + 1
        data["stats"]["flows_by_complexity"][complexity] = \
            data["stats"]["flows_by_complexity"].get(complexity, 0) + 1

    conn.close()

    # Write to JSON file
    output_file = Path(output_path)
    output_file.parent.mkdir(parents=True, exist_ok=True)

    with open(output_file, 'w', encoding='utf-8') as f:
        json.dump(data, f, indent=2, ensure_ascii=False)

    print(f"✅ Exported execution flows to {output_path}")
    print(f"📊 Statistics:")
    print(f"   - Flows: {data['stats']['total_flows']}")
    print(f"   - Top-level steps: {data['stats']['total_steps']}")
    print(f"   - Primary flows: {data['stats']['primary_flows']}")
    print(f"\n📦 Flows by type:")
    for flow_type, count in sorted(data['stats']['flows_by_type'].items()):
        print(f"   - {flow_type}: {count}")
    print(f"\n🔧 Flows by complexity:")
    for complexity, count in sorted(data['stats']['flows_by_complexity'].items()):
        print(f"   - {complexity}: {count}")

    # Print flow details
    print(f"\n🔄 Flows:")
    for flow in data["flows"]:
        primary_mark = "⭐" if flow["is_primary"] else "  "
        print(f"{primary_mark} {flow['name']} ({flow['complexity']})")
        print(f"     Trigger: {flow['trigger']}")
        print(f"     Steps: {len(flow['steps'])} top-level")

        # Count total steps including substeps
        def count_all_steps(steps):
            count = len(steps)
            for step in steps:
                count += count_all_steps(step.get('substeps', []))
            return count

        total_steps = count_all_steps(flow['steps'])
        print(f"     Total steps (all levels): {total_steps}")
        print()

if __name__ == "__main__":
    db_path = ".clarity/ai-coding-agent.db"
    output_path = "flow-data.json"
    export_flows_to_json(db_path, output_path)
