"""
Generate Complete Architecture Blueprint for ClarAIty IDE

This uses ClarAIty to plan the full integrated AI coding IDE with:
- Chat interface for agent interaction
- Real-time architecture visualization
- Blueprint approval workflow
- Execution monitoring
- File preview and editing

Designed with Anthropic-level architectural principles.
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
    """Generate complete IDE blueprint using ClarAIty."""
    print("="*80)
    print("🏗️  ClarAIty IDE - Principal Architect Blueprint Generation")
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

    # Comprehensive task description
    task = """
Build a production-grade web-based IDE for ClarAIty AI Coding Agent following Anthropic's architectural principles.

**VISION:**
Create a unified interface that combines the best of Claude Code (chat-based interaction) with unique architecture visualization capabilities. The IDE should feel responsive, intelligent, and provide unprecedented visibility into the AI's reasoning and code structure.

**CORE PRINCIPLES:**

1. **Separation of Concerns:**
   - Presentation layer (React components)
   - Business logic (hooks, services)
   - State management (Zustand stores)
   - API communication (REST + WebSocket)

2. **Performance First:**
   - Virtual scrolling for large lists
   - Debounced search and filters
   - Lazy loading for heavy components
   - WebSocket for real-time updates (not polling)

3. **Resilience:**
   - Graceful degradation when backend is down
   - Retry logic with exponential backoff
   - Error boundaries for component failures
   - Optimistic UI updates with rollback

4. **User Experience:**
   - < 100ms response for interactions
   - Loading states for all async operations
   - Clear error messages with recovery actions
   - Keyboard shortcuts for power users

**FEATURE REQUIREMENTS:**

**1. Chat Interface (Primary Interaction)**
   - Left panel or bottom panel (collapsible)
   - Chat history with message threading
   - Markdown rendering with code syntax highlighting
   - File references are clickable and open in preview
   - Task submission with streaming responses
   - Quick actions: "Explain this", "Fix bug", "Refactor"
   - Chat history persists across sessions

**2. Architecture Visualization (Unique Value)**
   - Center canvas with React Flow
   - Interactive node-based graph of code components
   - Color-coded by layer (core, tools, memory, workflow, etc.)
   - Edge relationships (calls, imports, depends_on, etc.)
   - Zoom, pan, fit-to-screen controls
   - Search components (highlights matches)
   - Filter by layer, type, or custom query
   - Click node → show details in right panel
   - Real-time updates via WebSocket

**3. Component Details Panel (Context)**
   - Right sidebar (collapsible)
   - Shows selected component info:
     - Name, type, purpose, layer
     - File path (clickable → preview)
     - Key methods/functions
     - Dependencies (clickable)
     - Relationships (incoming/outgoing)
     - Design decisions
   - Syntax-highlighted code preview
   - "Edit" button opens in future editor view

**4. Blueprint Approval Workflow**
   - Modal overlay when blueprint generated
   - 3-column layout:
     - Left: Component list (expandable tree)
     - Center: Selected component details
     - Right: Design decisions + rationale
   - File actions summary (create/modify/delete)
   - Complexity and time estimate
   - Prerequisites and risks
   - Approve/Reject buttons
   - Feedback textarea for rejection
   - "Regenerate with feedback" option

**5. Execution Monitoring (Transparency)**
   - Bottom panel (expandable, like VSCode terminal)
   - Shows real-time task execution:
     - Workflow state (analyzing → planning → executing → verifying)
     - Current step with progress indicator
     - Tool calls and results
     - Verification checks
     - Final report
   - Collapsible sections for each step
   - Copy button for logs
   - Filter by info/warning/error

**6. Task Queue & History**
   - Top bar shows active task
   - Click to expand queue (shows pending/running/completed)
   - Each task shows: description, status, duration
   - Click completed task → view full execution log
   - Re-run or modify past tasks

**TECHNICAL ARCHITECTURE:**

**Frontend Stack:**
- React 18 with TypeScript (strict mode)
- Vite for build tooling (fast HMR)
- React Flow for graph visualization
- Zustand for state management (simpler than Redux)
- React Query for server state (caching, refetching)
- TailwindCSS for styling (utility-first)
- Monaco Editor for code preview/editing
- React Markdown for chat rendering
- Framer Motion for animations (optional)

**State Management:**
- `uiStore`: Layout state (panel sizes, collapsed state)
- `chatStore`: Chat history, message streaming
- `architectureStore`: Graph data, selected components
- `taskStore`: Task queue, execution state
- `blueprintStore`: Current blueprint under review
- React Query for server data (components, relationships)

**API Layer:**
- REST endpoints for CRUD:
  - GET/POST /api/chat/messages
  - GET /api/components (with pagination)
  - GET /api/components/{id}
  - GET /api/relationships
  - POST /api/tasks (submit new task)
  - GET /api/tasks/{id} (get task status)
  - GET /api/blueprints/{id}
  - PUT /api/blueprints/{id}/approve
  - PUT /api/blueprints/{id}/reject
- WebSocket for real-time:
  - /ws/chat/{session_id} (streaming responses)
  - /ws/architecture/{session_id} (component updates)
  - /ws/tasks/{task_id} (execution progress)

**Component Architecture:**

1. **Layout Components:**
   - `AppLayout`: Main 3-panel layout with resizable splitters
   - `Header`: Project name, settings, user menu
   - `StatusBar`: Active task, connection status

2. **Chat Components:**
   - `ChatPanel`: Container for chat interface
   - `ChatHistory`: Scrollable message list (virtual scroll)
   - `ChatMessage`: Single message with markdown rendering
   - `ChatInput`: Text input with keyboard shortcuts
   - `QuickActions`: Preset action buttons

3. **Architecture Components:**
   - `ArchitectureCanvas`: React Flow wrapper
   - `ComponentNode`: Custom node for React Flow
   - `GraphControls`: Zoom, pan, fit, search controls
   - `LayerFilter`: Filter by layer checkboxes

4. **Details Components:**
   - `DetailsPanel`: Container for component details
   - `ComponentInfo`: Basic component information
   - `CodePreview`: Monaco editor (read-only)
   - `RelationshipList`: Clickable list of relationships

5. **Blueprint Components:**
   - `BlueprintModal`: Full-screen modal for approval
   - `ComponentTree`: Left sidebar tree view
   - `ComponentDetails`: Center detail view
   - `DesignDecisions`: Right sidebar decisions
   - `ApprovalActions`: Approve/Reject buttons

6. **Execution Components:**
   - `ExecutionPanel`: Bottom panel container
   - `WorkflowStatus`: State machine visualization
   - `ExecutionLog`: Streaming log output
   - `ToolCallCard`: Individual tool execution

7. **Shared Components:**
   - `Button`, `Input`, `Select`: Styled form elements
   - `Modal`, `Drawer`, `Tooltip`: Layout primitives
   - `LoadingSpinner`, `ErrorBoundary`, `EmptyState`

**Hooks:**
- `useChat()`: Chat state and actions
- `useComponents()`: Fetch and cache components (React Query)
- `useWebSocket()`: Generic WebSocket hook with reconnection
- `useTaskExecution()`: Subscribe to task progress
- `useArchitectureGraph()`: Transform data for React Flow
- `useKeyboardShortcuts()`: Global keyboard shortcuts

**Services:**
- `apiClient.ts`: Axios instance with interceptors
- `websocketService.ts`: WebSocket connection manager
- `authService.ts`: Auth token management (future)
- `storageService.ts`: LocalStorage wrapper

**PROJECT STRUCTURE:**
```
clarity-ui/
├── public/                  # Static assets
├── src/
│   ├── components/
│   │   ├── layout/         # AppLayout, Header, StatusBar
│   │   ├── chat/           # Chat interface components
│   │   ├── architecture/   # Graph visualization
│   │   ├── details/        # Component details panel
│   │   ├── blueprint/      # Blueprint approval
│   │   ├── execution/      # Execution monitoring
│   │   └── shared/         # Reusable UI components
│   ├── hooks/
│   │   ├── useChat.ts
│   │   ├── useComponents.ts
│   │   ├── useWebSocket.ts
│   │   ├── useTaskExecution.ts
│   │   └── useArchitectureGraph.ts
│   ├── stores/
│   │   ├── uiStore.ts
│   │   ├── chatStore.ts
│   │   ├── architectureStore.ts
│   │   ├── taskStore.ts
│   │   └── blueprintStore.ts
│   ├── services/
│   │   ├── apiClient.ts
│   │   ├── websocketService.ts
│   │   └── storageService.ts
│   ├── types/
│   │   ├── api.ts          # API request/response types
│   │   ├── clarity.ts      # Domain types (Component, Blueprint, etc.)
│   │   ├── chat.ts         # Chat message types
│   │   └── task.ts         # Task execution types
│   ├── utils/
│   │   ├── graphLayout.ts  # React Flow layout algorithms
│   │   ├── markdown.ts     # Markdown utilities
│   │   └── colors.ts       # Color schemes for layers
│   ├── App.tsx
│   ├── main.tsx
│   └── index.css
├── package.json
├── tsconfig.json
├── vite.config.ts
├── tailwind.config.js
└── postcss.config.js
```

**KEY DESIGN DECISIONS:**

1. **React Flow over D3.js:**
   - Better React integration, less imperative code
   - Built-in zoom/pan/selection
   - Easy custom nodes

2. **Zustand over Redux:**
   - Simpler API, less boilerplate
   - No context provider hell
   - Better TypeScript support

3. **React Query for server state:**
   - Automatic caching and refetching
   - Stale-while-revalidate strategy
   - Handles loading/error states

4. **Vite over Create React App:**
   - 10-100x faster HMR
   - Native ES modules
   - Better TypeScript support

5. **Monaco over CodeMirror:**
   - Same editor as VSCode
   - Better TypeScript IntelliSense (future)
   - Mature and well-maintained

6. **WebSocket over polling:**
   - Real-time updates with low latency
   - Reduced server load
   - Better for streaming responses

7. **TailwindCSS over styled-components:**
   - Faster development
   - Smaller bundle size
   - Consistent design system

**IMPLEMENTATION PHASES:**

**Phase 1: Foundation (3-4 days)**
- Setup Vite + React + TypeScript
- Install dependencies
- Create basic layout with resizable panels
- Setup Zustand stores (empty)
- Setup React Query
- API client with mock data

**Phase 2: Architecture Visualization (2-3 days)**
- Implement React Flow graph
- Custom node components
- Graph controls (zoom, pan, search)
- Layer filtering
- Connect to FastAPI backend
- WebSocket for real-time updates

**Phase 3: Chat Interface (2-3 days)**
- Chat panel with message history
- Message rendering (markdown, code)
- Chat input with keyboard shortcuts
- Streaming response handling
- WebSocket integration
- Task submission

**Phase 4: Component Details (1-2 days)**
- Details panel layout
- Component info display
- Code preview with Monaco
- Relationship list
- File preview

**Phase 5: Blueprint Approval (2 days)**
- Modal layout
- Component tree navigation
- Detail view with design decisions
- Approve/Reject actions
- Feedback form

**Phase 6: Execution Monitoring (2 days)**
- Execution panel
- Workflow state display
- Log streaming
- Tool call visualization
- Collapsible sections

**Phase 7: Polish & Testing (2-3 days)**
- Responsive design
- Loading states
- Error boundaries
- Keyboard shortcuts
- Performance optimization
- E2E testing

**BACKEND REQUIREMENTS:**

New FastAPI endpoints needed:
- POST /api/chat/messages (submit message, get streaming response)
- GET /api/chat/sessions/{id}/messages (get history)
- POST /api/tasks (submit task to agent)
- GET /api/tasks/{id} (get task status)
- GET /api/tasks/{id}/logs (get execution logs)
- WS /ws/chat/{session_id} (streaming chat)
- WS /ws/tasks/{task_id} (streaming execution)

**SUCCESS CRITERIA:**
- Chat interface responds < 100ms to user input
- Graph renders 500+ components smoothly (60fps)
- WebSocket reconnects automatically
- All async operations have loading states
- Error messages are actionable
- Works on desktop browsers (Chrome, Firefox, Safari)
- TypeScript strict mode with zero errors
- 80%+ test coverage

Generate a complete architecture blueprint with all components, design decisions, relationships, and file actions.
"""

    # Generate blueprint
    print("Step 2: Generating comprehensive architecture blueprint...")
    print("(This will take ~60-90 seconds due to complexity)")
    print()

    try:
        blueprint = generator.generate_blueprint(
            task_description=task,
            codebase_context="Existing FastAPI backend with ClarAIty database, CodeAnalyzer, and basic REST endpoints"
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
        print("   Opening in browser at http://localhost:8765...")
        print()

        approval_server = ApprovalServer(
            blueprint=blueprint,
            port=8765
        )

        decision = approval_server.start_and_wait(auto_open=True)

        print()
        print("="*80)

        if decision.approved:
            print("✅ BLUEPRINT APPROVED!")
            print("="*80)
            print()
            print("📋 Implementation Guide:")
            print()
            print("The blueprint has been approved. Key next steps:")
            print()
            print("1. Setup Phase:")
            print("   - Create React project with Vite")
            print("   - Install all dependencies")
            print("   - Configure TypeScript, Tailwind, ESLint")
            print()
            print("2. Foundation:")
            for i, comp in enumerate(blueprint.components[:5], 1):
                print(f"   {i}. {comp.name} - {comp.purpose[:60]}...")
            print()
            print(f"3. Continue with remaining {len(blueprint.components) - 5} components")
            print()
            print("4. Integration & Testing")
            print()
            print("="*80)
            print("✅ Ready to implement!")
            print("="*80)

        else:
            print("❌ BLUEPRINT REJECTED")
            print("="*80)
            print()
            if decision.feedback:
                print(f"Feedback: {decision.feedback}")
                print()
            print("You can:")
            print("  1. Refine the requirements")
            print("  2. Run this script again")
            print("  3. Or manually adjust the architecture")

    except Exception as e:
        print(f"❌ Error: {e}")
        import traceback
        traceback.print_exc()
        sys.exit(1)


if __name__ == "__main__":
    main()
