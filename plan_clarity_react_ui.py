"""
Use ClarAIty to Plan the React UI Implementation

This demonstrates ClarAIty's "Generate New" mode by using it to plan
the architecture for its own React UI!

Meta moment: ClarAIty planning ClarAIty 🎯
"""

import sys
import os
from pathlib import Path

# Fix Windows console encoding
if sys.platform == 'win32':
    import io
    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8')
    sys.stderr = io.TextIOWrapper(sys.stderr.buffer, encoding='utf-8')

# Add src to path
sys.path.insert(0, str(Path(__file__).parent))

# Ensure API key
if not os.getenv("DASHSCOPE_API_KEY"):
    print("⚠️  DASHSCOPE_API_KEY environment variable not set")
    sys.exit(1)


def main():
    """Plan the React UI using ClarAIty."""
    print("="*80)
    print("🎨 Using ClarAIty to Plan ClarAIty React UI")
    print("="*80)
    print()
    print("This will:")
    print("  1. Generate an architecture blueprint for the React UI")
    print("  2. Show you the plan in your browser")
    print("  3. Wait for your approval")
    print("  4. Then we can implement based on the approved blueprint")
    print()

    from src.core import CodingAgent

    # Initialize agent with ClarAIty enabled
    print("Initializing agent with ClarAIty enabled...")
    agent = CodingAgent(
        model_name="qwen-plus",
        backend="openai",
        base_url="https://dashscope-intl.aliyuncs.com/compatible-mode/v1",
        context_window=131072,
        working_directory=".",
        api_key_env="DASHSCOPE_API_KEY",
        enable_clarity=True  # This is the key!
    )

    if not agent.clarity_hook:
        print("❌ ClarAIty not enabled!")
        sys.exit(1)

    print("✅ ClarAIty enabled")
    print(f"   Mode: {agent.clarity_hook.config.mode}")
    print()

    # Define the task - building the React UI
    task = """
Build a production-grade React UI for ClarAIty with the following features:

**Core Requirements:**

1. **Architecture Visualization**
   - Interactive component graph using React Flow
   - Nodes represent components, edges represent relationships
   - Color-coded by layer (core, memory, workflow, tools, etc.)
   - Zoom, pan, filter, search capabilities
   - Click nodes to show component details panel

2. **Component Browser**
   - Sidebar with tree view of all components
   - Group by layer
   - Search and filter functionality
   - Show component count per layer
   - Click to highlight in graph

3. **Component Details Panel**
   - Show when component is selected
   - Display: name, type, purpose, layer, file path
   - Show related artifacts (files, classes, methods)
   - Show incoming/outgoing relationships
   - Show design decisions (if any)

4. **Real-Time Sync Indicator**
   - WebSocket connection to backend
   - Show sync status (idle, syncing, error)
   - Display last sync time
   - Show number of files analyzed

5. **Blueprint Approval Interface**
   - Better UX than current HTML approval
   - Show generated blueprint with expandable sections
   - Inline editing of component details
   - Approve/Reject buttons with feedback form
   - Show AI-generated design rationale

**Technical Stack:**
- React 18 with TypeScript
- React Flow for graph visualization
- TailwindCSS for styling
- Zustand for state management
- React Query for API calls
- WebSocket for real-time updates
- Vite for build tooling

**Architecture:**
- `clarity-ui/` - React app root
- `clarity-ui/src/components/` - React components
- `clarity-ui/src/hooks/` - Custom hooks
- `clarity-ui/src/api/` - API client
- `clarity-ui/src/stores/` - Zustand stores
- `clarity-ui/src/types/` - TypeScript types

**Integration:**
- Connect to existing FastAPI backend (port 8766)
- Use existing REST endpoints from `src/clarity/api/endpoints.py`
- Use WebSocket endpoint `/ws/clarity/{session_id}`
- Serve from FastAPI as static files in production

**Key Design Decisions:**
1. Use React Flow instead of D3.js for better React integration
2. Use Zustand for simpler state management than Redux
3. Use React Query for automatic caching and refetching
4. Use Vite for faster development builds
5. Component-first architecture for reusability

Please generate a complete architecture blueprint with:
- All React components needed
- Data flow and state management
- API integration points
- File structure
- Component relationships
"""

    print("📋 Submitting task to ClarAIty...")
    print()
    print("⏳ ClarAIty will now:")
    print("   1. Analyze the task complexity")
    print("   2. Generate an architecture blueprint")
    print("   3. Open the approval UI in your browser")
    print("   4. Wait for you to approve or reject")
    print()

    try:
        response = agent.execute_task(
            task_description=task,
            task_type="implement",
            use_rag=False,
            stream=False,
            force_direct=True  # Force direct mode to trigger ClarAIty
        )

        print()
        print("="*80)
        print("✅ Blueprint Generation Complete!")
        print("="*80)
        print()

        metadata = response.metadata

        if "clarity_blueprint" in agent.memory.metadata:
            blueprint_data = agent.memory.metadata["clarity_blueprint"]
            print("📊 Blueprint Summary:")
            print(f"   Components: {len(blueprint_data.get('components', []))}")
            print(f"   Design Decisions: {len(blueprint_data.get('design_decisions', []))}")
            print(f"   File Actions: {len(blueprint_data.get('file_actions', []))}")
            print(f"   Relationships: {len(blueprint_data.get('relationships', []))}")
            print()
            print("✅ Blueprint approved! Ready to implement.")
            print()
            print("Next steps:")
            print("  1. Review the blueprint details above")
            print("  2. Start implementation based on approved architecture")
            print("  3. Use the blueprint as a guide for component structure")
        elif metadata.get('clarity_status') == 'rejected':
            print("❌ Blueprint was rejected")
            print(f"   Feedback: {metadata.get('clarity_feedback', 'None')}")
            print()
            print("You can:")
            print("  1. Refine the task description")
            print("  2. Run this script again with updated requirements")
        else:
            print("ℹ️  ClarAIty was not triggered (task may be too simple)")
            print("   Response:", response.content[:200])

    except Exception as e:
        print(f"❌ Error: {e}")
        import traceback
        traceback.print_exc()
        sys.exit(1)


if __name__ == "__main__":
    main()
