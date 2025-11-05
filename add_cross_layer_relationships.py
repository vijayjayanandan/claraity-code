"""
Add cross-layer relationships to the database for architecture visualization
"""
import sys
sys.path.insert(0, "C:\\Vijay\\Learning\\AI\\ai-coding-agent")

from src.clarity.core.database.clarity_db import ClarityDB

db = ClarityDB(".clarity/ai-coding-agent.db")

# Define cross-layer relationships based on actual architecture
# Format: (source_component_id, target_component_id, relationship_type, description, criticality)
cross_layer_relationships = [
    # Core -> Memory
    ("CODINGAGENT", "MEMORYMANAGER", "uses", "CodingAgent uses MemoryManager for context management", "high"),
    ("CODINGAGENT", "WORKINGMEMORY", "uses", "CodingAgent uses WorkingMemory for active context", "high"),

    # Core -> RAG
    ("CODINGAGENT", "RAGSYSTEM", "uses", "CodingAgent uses RAGSystem for code retrieval", "high"),
    ("CONTEXTBUILDER", "RAGSYSTEM", "uses", "ContextBuilder uses RAGSystem for context enrichment", "medium"),

    # Core -> Tools
    ("CODINGAGENT", "TOOL", "uses", "CodingAgent uses Tools for execution", "high"),

    # Core -> Workflow
    ("CODINGAGENT", "EXECUTIONENGINE", "uses", "CodingAgent uses ExecutionEngine for task execution", "high"),
    ("CODINGAGENT", "TASKANALYZER", "uses", "CodingAgent uses TaskAnalyzer for task classification", "high"),
    ("CODINGAGENT", "TASKPLANNER", "uses", "CodingAgent uses TaskPlanner for planning", "high"),

    # Core -> LLM
    ("CODINGAGENT", "LLMBACKEND", "uses", "CodingAgent uses LLMBackend for AI interactions", "high"),

    # Workflow -> Tools
    ("EXECUTIONENGINE", "TOOL", "uses", "ExecutionEngine uses Tools for step execution", "high"),
    ("VERIFICATIONLAYER", "TOOL", "uses", "VerificationLayer uses Tools for verification", "medium"),

    # Workflow -> Memory
    ("EXECUTIONENGINE", "MEMORYMANAGER", "uses", "ExecutionEngine uses MemoryManager for execution context", "medium"),
    ("TASKANALYZER", "MEMORYMANAGER", "uses", "TaskAnalyzer uses MemoryManager for analysis context", "medium"),

    # Workflow -> LLM
    ("TASKPLANNER", "LLMBACKEND", "uses", "TaskPlanner uses LLMBackend for plan generation", "high"),
    ("VERIFICATIONLAYER", "LLMBACKEND", "uses", "VerificationLayer uses LLMBackend for verification", "medium"),

    # Memory -> RAG
    ("MEMORYMANAGER", "RAGSYSTEM", "uses", "MemoryManager uses RAGSystem for semantic retrieval", "medium"),
    ("SEMANTICMEMORY", "RAGSYSTEM", "uses", "SemanticMemory uses RAGSystem for storage", "high"),

    # RAG -> Tools
    ("RAGSYSTEM", "READFILETOOL", "uses", "RAGSystem uses ReadFileTool for file access", "medium"),

    # Tools -> LLM (for code analysis tools)
    ("ANALYZECODETOOL", "LLMBACKEND", "uses", "AnalyzeCodeTool uses LLMBackend for analysis", "medium"),
]

print(f"Adding {len(cross_layer_relationships)} cross-layer relationships...")

added = 0
skipped = 0

for source_id, target_id, rel_type, description, criticality in cross_layer_relationships:
    try:
        # Check if components exist
        source = db.get_component(source_id)
        target = db.get_component(target_id)

        if not source:
            print(f"  [SKIP] Source component not found: {source_id}")
            skipped += 1
            continue

        if not target:
            print(f"  [SKIP] Target component not found: {target_id}")
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

        print(f"  [ADD] {source['name']} ({source.get('layer','?')}) --{rel_type}--> {target['name']} ({target.get('layer','?')})")
        added += 1

    except Exception as e:
        print(f"  [ERROR] Failed to add {source_id} -> {target_id}: {e}")
        skipped += 1

print(f"\nDone! Added {added} relationships, skipped {skipped}")

# Verify
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
