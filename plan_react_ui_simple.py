"""
Use ClarAIty Generator to Plan React UI

Simplified version that uses ClarityGenerator directly.
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
    """Generate React UI blueprint using ClarAIty."""
    print("="*80)
    print("🎨 ClarAIty: Planning React UI Architecture")
    print("="*80)
    print()

    from src.clarity.core.generator import ClarityGenerator
    from src.clarity.ui.approval import ApprovalServer

    # Initialize generator
    print("Step 1: Initializing ClarityGenerator...")
    generator = ClarityGenerator(
        model_name="qwen-plus",
        base_url="https://dashscope-intl.aliyuncs.com/compatible-mode/v1",
        api_key_env="DASHSCOPE_API_KEY"
    )
    print("✅ Generator ready")
    print()

    # Task description
    task = """
Build a production-grade React UI for ClarAIty with the following features:

**Core Requirements:**

1. **Architecture Visualization Page**
   - Interactive component graph using React Flow
   - Nodes represent components, edges represent relationships
   - Color-coded by layer (core, memory, workflow, tools, etc.)
   - Zoom, pan, filter, search capabilities
   - Click nodes to show component details

2. **Component Browser Sidebar**
   - Tree view of all components grouped by layer
   - Search and filter functionality
   - Show component count per layer
   - Click to select/highlight in graph

3. **Component Details Panel**
   - Slides in when component selected
   - Display: name, type, purpose, layer, file path
   - Show related artifacts (files, classes, methods)
   - Show incoming/outgoing relationships
   - Show design decisions

4. **Real-Time Sync Indicator**
   - WebSocket connection to backend
   - Show sync status (idle, syncing, error)
   - Display last sync time
   - Notification toast for new components

5. **Blueprint Approval Page**
   - Better UX than current HTML approval
   - Show generated blueprint with expandable sections
   - Inline editing of component details
   - Approve/Reject buttons with feedback textarea
   - Show AI-generated design rationale

**Technical Stack:**
- React 18 with TypeScript
- React Flow for graph visualization
- TailwindCSS for styling
- Zustand for state management
- React Query for API calls
- WebSocket for real-time updates
- Vite for build tooling

**Project Structure:**
```
clarity-ui/
├── src/
│   ├── components/
│   │   ├── ArchitectureGraph.tsx
│   │   ├── ComponentBrowser.tsx
│   │   ├── ComponentDetails.tsx
│   │   ├── BlueprintApproval.tsx
│   │   └── SyncIndicator.tsx
│   ├── hooks/
│   │   ├── useComponents.ts
│   │   ├── useWebSocket.ts
│   │   └── useArchitectureData.ts
│   ├── api/
│   │   └── clarityClient.ts
│   ├── stores/
│   │   └── architectureStore.ts
│   ├── types/
│   │   └── clarity.ts
│   └── App.tsx
├── package.json
├── vite.config.ts
└── tsconfig.json
```

**Integration Points:**
- Connect to FastAPI backend at http://localhost:8766
- Use REST endpoints: /api/clarity/components, /api/clarity/relationships
- Use WebSocket: /ws/clarity/{session_id}
- Serve as static files from FastAPI in production

**Key Design Decisions:**
1. React Flow for better React integration than D3.js
2. Zustand for simpler state management than Redux
3. React Query for automatic caching and refetching
4. Vite for faster development builds than Create React App
5. TypeScript for type safety with backend API

Generate a complete architecture blueprint with all components, relationships, and file structure.
"""

    # Generate blueprint
    print("Step 2: Generating architecture blueprint...")
    print("(This will take ~30-60 seconds)")
    print()

    try:
        blueprint = generator.generate_blueprint(
            task_description=task,
            codebase_context="Existing FastAPI backend with REST endpoints and WebSocket support"
        )

        print("✅ Blueprint generated!")
        print()
        print(f"📊 Blueprint Summary:")
        print(f"   Components: {len(blueprint.components)}")
        print(f"   Design Decisions: {len(blueprint.design_decisions)}")
        print(f"   File Actions: {len(blueprint.file_actions)}")
        print(f"   Relationships: {len(blueprint.relationships)}")
        print(f"   Complexity: {blueprint.estimated_complexity}")
        print(f"   Estimated Time: {blueprint.estimated_time}")
        print()

        # Show approval UI
        print("Step 3: Launching approval UI...")
        print("   Opening in browser...")
        print()

        approval_server = ApprovalServer(
            blueprint=blueprint,
            port=8765
        )

        decision = approval_server.start_and_wait(auto_open=True)

        print()
        print("="*80)

        if decision.approved:
            print("✅ Blueprint APPROVED!")
            print("="*80)
            print()
            print("📋 Approved Architecture:")
            print()
            print("Components to build:")
            for comp in blueprint.components:
                print(f"  • {comp.name} ({comp.type})")
                print(f"    Purpose: {comp.purpose[:80]}...")
                print()

            print("Design Decisions:")
            for decision in blueprint.design_decisions:
                print(f"  • {decision.decision}")
                print(f"    Rationale: {decision.rationale[:80]}...")
                print()

            print("File Actions:")
            for action in blueprint.file_actions:
                print(f"  • {action.action}: {action.file_path}")
                print()

            print("="*80)
            print("✅ Ready to implement!")
            print("="*80)
            print()
            print("Next steps:")
            print("  1. Set up React project with Vite")
            print("  2. Install dependencies (React Flow, TailwindCSS, Zustand, etc.)")
            print("  3. Implement components following the blueprint")
            print("  4. Connect to FastAPI backend")
            print("  5. Test and iterate")

        else:
            print("❌ Blueprint REJECTED")
            print("="*80)
            print()
            if decision.feedback:
                print(f"Feedback: {decision.feedback}")
                print()
            print("You can:")
            print("  1. Refine the requirements")
            print("  2. Run this script again")
            print("  3. Or manually plan the architecture")

    except Exception as e:
        print(f"❌ Error: {e}")
        import traceback
        traceback.print_exc()
        sys.exit(1)


if __name__ == "__main__":
    main()
