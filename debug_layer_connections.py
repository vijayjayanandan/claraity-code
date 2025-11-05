"""
Debug script for layer connections issue
"""
import sys
sys.path.insert(0, "C:\\Vijay\\Learning\\AI\\ai-coding-agent")

from src.clarity.core.database.clarity_db import ClarityDB

db = ClarityDB(".clarity/ai-coding-agent.db")

# Get all components
components = db.get_all_components()
print(f"Total components: {len(components)}")

# Build component ID to layer mapping
component_to_layer = {comp['id']: comp.get('layer', 'other') for comp in components}
print(f"\nComponent to layer mapping (first 5):")
for i, (comp_id, layer) in enumerate(list(component_to_layer.items())[:5]):
    print(f"  {comp_id}: {layer}")

# Get all relationships
all_relationships = db.get_all_relationships()
print(f"\nTotal relationships: {len(all_relationships)}")
print(f"\nFirst relationship:")
if all_relationships:
    rel = all_relationships[0]
    print(f"  ID: {rel['id']}")
    print(f"  source_id: {rel['source_id']}")
    print(f"  target_id: {rel['target_id']}")
    print(f"  relationship_type: {rel['relationship_type']}")
    print(f"  All keys: {list(rel.keys())}")

# Derive layer-to-layer connections
layer_connections = {}
for rel in all_relationships:
    source_id = rel.get('source_id')
    target_id = rel.get('target_id')

    print(f"\nProcessing relationship:")
    print(f"  source_id: {source_id}")
    print(f"  target_id: {target_id}")

    from_layer = component_to_layer.get(source_id, 'other')
    to_layer = component_to_layer.get(target_id, 'other')

    print(f"  from_layer: {from_layer}")
    print(f"  to_layer: {to_layer}")

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
        print(f"  [ADDED] Added to layer connections: {key}")
    else:
        print(f"  [SKIPPED] Same layer")

print(f"\nTotal layer connections: {len(layer_connections)}")
print(f"\nLayer connections:")
for key, conn in layer_connections.items():
    print(f"  {key}: {conn['count']} connections, types: {conn['types']}")
