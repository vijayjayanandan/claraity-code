#!/usr/bin/env python3
"""Prepare unified data for ClarAIty complete interface."""

import json
from pathlib import Path
from collections import defaultdict

def build_file_tree(artifacts, components):
    """Build hierarchical file tree from artifacts."""

    # Create component lookup
    component_map = {c['id']: c for c in components}

    # Group artifacts by file
    files = defaultdict(lambda: {
        'artifacts': [],
        'components': set(),
        'layers': set(),
        'line_count': 0
    })

    for artifact in artifacts:
        file_path = artifact['file_path']
        files[file_path]['artifacts'].append(artifact)

        comp_id = artifact['component_id']
        if comp_id in component_map:
            comp = component_map[comp_id]
            files[file_path]['components'].add(comp['name'])
            files[file_path]['layers'].add(comp['layer'])

        # Estimate line count
        if artifact['line_end']:
            files[file_path]['line_count'] = max(
                files[file_path]['line_count'],
                artifact['line_end']
            )

    # Build directory tree
    tree = {}

    for file_path, file_data in files.items():
        parts = file_path.split('/')
        current = tree

        # Navigate/create directory structure
        for i, part in enumerate(parts[:-1]):
            if part not in current:
                current[part] = {'_type': 'dir', '_children': {}}
            current = current[part]['_children']

        # Add file
        filename = parts[-1]
        current[filename] = {
            '_type': 'file',
            'path': file_path,
            'components': list(file_data['components']),
            'layers': list(file_data['layers']),
            'artifact_count': len(file_data['artifacts']),
            'line_count': file_data['line_count'],
            'artifacts': file_data['artifacts']
        }

    return tree

def calculate_dir_stats(node):
    """Recursively calculate directory statistics."""
    if node.get('_type') == 'file':
        return {
            'files': 1,
            'artifacts': node.get('artifact_count', 0),
            'lines': node.get('line_count', 0)
        }

    stats = {'files': 0, 'artifacts': 0, 'lines': 0}

    if '_children' in node:
        for child in node['_children'].values():
            child_stats = calculate_dir_stats(child)
            stats['files'] += child_stats['files']
            stats['artifacts'] += child_stats['artifacts']
            stats['lines'] += child_stats['lines']

        node['_stats'] = stats

    return stats

def prepare_unified_data():
    """Combine all data sources into one unified JSON."""

    # Load existing data
    with open('clarity-data.json', 'r') as f:
        clarity_data = json.load(f)

    with open('flow-data.json', 'r') as f:
        flow_data = json.load(f)

    # Build file tree
    file_tree = build_file_tree(
        clarity_data['artifacts'],
        clarity_data['components']
    )

    # Calculate directory statistics
    calculate_dir_stats({'_type': 'dir', '_children': file_tree})

    # Create unified data structure
    unified = {
        'project': {
            'name': 'AI Coding Agent',
            'description': 'Production-ready AI agent with workflow automation, memory systems, and RAG-based code understanding',
            'version': '1.0.0',
            'repository': 'ai-coding-agent'
        },

        'stats': {
            'components': len(clarity_data['components']),
            'files': clarity_data['stats']['total_artifacts'],
            'relationships': len(clarity_data['relationships']),
            'flows': len(flow_data['flows']),
            'layers': len(clarity_data['stats']['components_by_layer']),
            'design_decisions': len(clarity_data['design_decisions'])
        },

        'components': clarity_data['components'],
        'relationships': clarity_data['relationships'],
        'artifacts': clarity_data['artifacts'],
        'design_decisions': clarity_data['design_decisions'],

        'flows': flow_data['flows'],

        'file_tree': file_tree,

        'layers': {
            layer: {
                'count': count,
                'components': [c['name'] for c in clarity_data['components'] if c['layer'] == layer]
            }
            for layer, count in clarity_data['stats']['components_by_layer'].items()
        },

        'capabilities': [
            {
                'name': 'Planning & Analysis',
                'description': 'Analyze tasks and create execution plans',
                'components': ['TaskAnalyzer', 'TaskPlanner'],
                'readiness': 95,
                'layer': 'workflow'
            },
            {
                'name': 'Execution',
                'description': 'Execute plans with tool integration',
                'components': ['ExecutionEngine', 'ToolExecutor'],
                'readiness': 100,
                'layer': 'workflow'
            },
            {
                'name': 'Verification',
                'description': 'Verify results and ensure quality',
                'components': ['VerificationLayer'],
                'readiness': 85,
                'layer': 'workflow'
            },
            {
                'name': 'Memory Management',
                'description': 'Context and learning across sessions',
                'components': ['MemoryManager', 'WorkingMemory', 'EpisodicMemory', 'SemanticMemory'],
                'readiness': 90,
                'layer': 'memory'
            },
            {
                'name': 'Code Understanding',
                'description': 'RAG-based semantic code search',
                'components': ['CodeIndexer', 'Embedder', 'HybridRetriever'],
                'readiness': 80,
                'layer': 'rag'
            }
        ],

        'entry_points': [
            {
                'name': 'User Input via CLI',
                'file': 'src/cli.py',
                'line': 131,
                'description': 'Main entry point for user interactions'
            },
            {
                'name': 'Agent Execution',
                'file': 'src/core/agent.py',
                'line': 150,
                'function': 'execute_task()',
                'description': 'Core task execution orchestration'
            }
        ]
    }

    # Write unified data
    with open('clarity-unified-data.json', 'w', encoding='utf-8') as f:
        json.dump(unified, f, indent=2, ensure_ascii=False)

    print(f"✅ Created clarity-unified-data.json")
    print(f"\n📊 Unified Data Summary:")
    print(f"   - Components: {unified['stats']['components']}")
    print(f"   - Files: {unified['stats']['files']}")
    print(f"   - Flows: {unified['stats']['flows']}")
    print(f"   - Capabilities: {len(unified['capabilities'])}")
    print(f"   - Layers: {unified['stats']['layers']}")
    print(f"   - Entry Points: {len(unified['entry_points'])}")

    # Calculate file size
    file_size = Path('clarity-unified-data.json').stat().st_size / 1024
    print(f"\n📦 File size: {file_size:.1f} KB")

if __name__ == "__main__":
    prepare_unified_data()
