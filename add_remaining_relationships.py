"""
Add relationships for the isolated layers (Hooks, Prompts, RAG, Subagents)
"""
import sys
sys.path.insert(0, "C:\\Vijay\\Learning\\AI\\ai-coding-agent")

from src.clarity.core.database.clarity_db import ClarityDB

db = ClarityDB(".clarity/ai-coding-agent.db")

# Define additional cross-layer relationships
additional_relationships = [
    # Core -> Hooks
    ("CODINGAGENT", "HOOKMANAGER", "uses", "CodingAgent uses HookManager for event hooks", "medium"),

    # Core -> Prompts
    ("CODINGAGENT", "PROMPTLIBRARY", "uses", "CodingAgent uses PromptLibrary for prompt templates", "high"),

    # Core -> Subagents
    ("CODINGAGENT", "SUBAGENTMANAGER", "uses", "CodingAgent uses SubAgentManager for delegation", "medium"),

    # Workflow -> Prompts
    ("TASKPLANNER", "PROMPTLIBRARY", "uses", "TaskPlanner uses PromptLibrary for planning prompts", "high"),

    # RAG -> Memory (RAG stores data in memory)
    ("CODEINDEXER", "SEMANTICMEMORY", "uses", "CodeIndexer uses SemanticMemory for storage", "high"),
    ("EMBEDDER", "SEMANTICMEMORY", "uses", "Embedder uses SemanticMemory for vector storage", "high"),

    # Tools -> Subagents
    ("DELEGATETOSUBAGENTTOOL", "SUBAGENTMANAGER", "uses", "DelegateToSubagentTool uses SubAgentManager", "high"),

    # Prompts -> LLM (prompts need LLM to render)
    ("PROMPTLIBRARY", "LLMBACKEND", "uses", "PromptLibrary uses LLMBackend for rendering", "medium"),
]

print(f"Adding {len(additional_relationships)} additional relationships...")

added = 0
skipped = 0

for source_id, target_id, rel_type, description, criticality in additional_relationships:
    try:
        # Check if components exist
        source = db.get_component(source_id)
        target = db.get_component(target_id)

        if not source:
            print(f"  [SKIP] Source not found: {source_id}")
            skipped += 1
            continue

        if not target:
            print(f"  [SKIP] Target not found: {target_id}")
            skipped += 1
            continue

        # Add relationship
        rel_id = db.add_component_relationship(
            source_id=source_id,
            target_id=target_id,
            relationship_type=rel_type,
            description=description,
            criticality=criticality
        )

        source_layer = source.get('layer', 'other')
        target_layer = target.get('layer', 'other')

        print(f"  [ADD] {source['name']} ({source_layer}) --{rel_type}--> {target['name']} ({target_layer})")
        added += 1

    except Exception as e:
        print(f"  [ERROR] {source_id} -> {target_id}: {e}")
        skipped += 1

print(f"\nDone! Added {added} relationships, skipped {skipped}")

# Show summary
all_rels = db.get_all_relationships()
print(f"\nTotal relationships in database: {len(all_rels)}")

# Count cross-layer
components = db.get_all_components()
component_to_layer = {comp['id']: comp.get('layer', 'other') for comp in components}

cross_layer_count = 0
for rel in all_rels:
    from_layer = component_to_layer.get(rel['source_id'], 'other')
    to_layer = component_to_layer.get(rel['target_id'], 'other')
    if from_layer != to_layer:
        cross_layer_count += 1

print(f"Cross-layer relationships: {cross_layer_count}")
