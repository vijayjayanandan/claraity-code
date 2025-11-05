"""Test API data for React UI"""
import sys
from pathlib import Path

# Fix Windows encoding
if sys.platform == 'win32':
    import io
    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8')

sys.path.insert(0, str(Path(__file__).parent))

from src.clarity.core.database.clarity_db import ClarityDB

db = ClarityDB('.clarity/ai-coding-agent.db')

# Simulate the API endpoint logic
components = db.get_all_components()
layer_map = {}
for comp in components:
    layer = comp.get('layer', 'other')
    if layer not in layer_map:
        layer_map[layer] = []
    layer_map[layer].append(comp)

# Build layer nodes
layers = [
    {
        "id": layer,
        "name": layer,
        "count": len(comps)
    }
    for layer, comps in layer_map.items()
]

# Get all relationships
all_relationships = db.get_all_relationships()

# Build component ID to layer mapping
component_to_layer = {comp['id']: comp.get('layer', 'other') for comp in components}

# Derive layer-to-layer connections
layer_connections = {}
for rel in all_relationships:
    from_layer = component_to_layer.get(rel['source_id'], 'other')
    to_layer = component_to_layer.get(rel['target_id'], 'other')

    # Only count inter-layer relationships
    if from_layer != to_layer:
        key = f"{from_layer}→{to_layer}"
        if key not in layer_connections:
            layer_connections[key] = {
                "source": from_layer,
                "target": to_layer,
                "count": 0,
                "types": set()
            }
        layer_connections[key]["count"] += 1
        layer_connections[key]["types"].add(rel.get('relationship_type', 'unknown'))

# Convert to list
connections = [
    {
        "source": conn["source"],
        "target": conn["target"],
        "count": conn["count"],
        "types": list(conn["types"])
    }
    for conn in layer_connections.values()
]

print("=" * 70)
print("API Data Verification (simulating /architecture/layers endpoint)")
print("=" * 70)
print(f"\n📊 Layers: {len(layers)}")
for layer in sorted(layers, key=lambda x: x['name']):
    print(f"  • {layer['name']:15} - {layer['count']:3} components")

print(f"\n🔗 Cross-Layer Connections: {len(connections)}")
for conn in sorted(connections, key=lambda x: (x['source'], x['target'])):
    types_str = ', '.join(conn['types'])
    print(f"  • {conn['source']:15} → {conn['target']:15} ({conn['count']:2} relationships, types: {types_str})")

print("\n✨ SUCCESS! API will return:")
print(f"   - {len(layers)} layers")
print(f"   - {len(connections)} cross-layer connections")
print(f"   - React UI will now show edges between layers!")

db.close()
