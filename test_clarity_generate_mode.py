#!/usr/bin/env python3
"""
Demo: ClarAIty Generate Mode

Test the Generate Mode by using ClarAIty to generate its own FastAPI server architecture.
This is the meta-demonstration: using ClarAIty to build ClarAIty itself!
"""

import os
import sys
import logging
from pathlib import Path

# Fix Windows console encoding for emojis
if sys.platform == 'win32':
    import io
    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8')
    sys.stderr = io.TextIOWrapper(sys.stderr.buffer, encoding='utf-8')

# Add src to path
sys.path.insert(0, str(Path(__file__).parent / "src"))

from clarity import ClarityGenerator, ApprovalServer, ApprovalDecision
from clarity.core.prompts import build_codebase_context

# Setup logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)


def main():
    """Run ClarAIty Generate Mode demo."""
    print("=" * 80)
    print("🚀 ClarAIty Generate Mode Demo")
    print("=" * 80)
    print()
    print("Task: Build ClarAIty FastAPI Server + React UI")
    print("This demonstrates using ClarAIty to generate its OWN architecture!")
    print()

    # Check for API key (optional - generator will check env vars)
    api_key = os.getenv("DASHSCOPE_API_KEY") or os.getenv("OPENAI_API_KEY")
    if not api_key:
        print("⚠️  Warning: No API key found in environment variables")
        print("   Set DASHSCOPE_API_KEY or OPENAI_API_KEY")
        print()
        print("Attempting to continue (generator will check environment)...")
    else:
        print("✅ API key found in environment")
    print()

    # Task description
    task_description = """
Build ClarAIty FastAPI Server and React UI Integration

Requirements:
1. FastAPI server with REST endpoints for:
   - GET /api/blueprint - Get current blueprint
   - POST /api/blueprint - Create new blueprint
   - PUT /api/blueprint/approve - Approve blueprint
   - PUT /api/blueprint/reject - Reject blueprint with feedback

2. WebSocket endpoint for real-time updates:
   - /ws/blueprint - Stream blueprint generation progress

3. React UI integration:
   - Serve static React build from /ui
   - Hot reload support for development

4. Architecture:
   - FastAPI app in src/clarity/api/server.py
   - WebSocket handler in src/clarity/api/websocket.py
   - Blueprint state manager in src/clarity/api/state.py
   - React UI in src/clarity/ui/react/ (placeholder for now)

5. Features:
   - CORS middleware for React development
   - Pydantic models for request/response validation
   - Error handling and logging
   - Blueprint persistence (in-memory for MVP)
"""

    # Build codebase context
    codebase_context = build_codebase_context(
        project_name="AI Coding Agent - ClarAIty Module",
        key_dirs=[
            "src/clarity/core/ - Blueprint data structures and generator",
            "src/clarity/ui/ - Approval UI (currently simple HTTP server)",
            "src/core/ - Agent core (CodingAgent, context builder)",
            "src/llm/ - LLM backends (OpenAI, Ollama)",
        ],
        key_files=[
            "src/clarity/core/blueprint.py - Blueprint data classes",
            "src/clarity/core/generator.py - ClarityGenerator (LLM-based)",
            "src/clarity/ui/approval.py - Simple approval HTTP server",
        ],
        patterns=[
            "Use dataclasses for data structures",
            "Use type hints everywhere",
            "Follow existing LLM backend patterns (src/llm/)",
            "Use Pydantic BaseModel for API models",
            "Keep separation: core (logic) vs api (REST) vs ui (frontend)",
        ],
    )

    # Step 1: Generate Blueprint
    print("📋 Step 1: Generating architecture blueprint with LLM...")
    print()

    try:
        # Generator will automatically use DASHSCOPE_API_KEY env var
        generator = ClarityGenerator(
            model_name="qwen-plus",
            # base_url and api_key will be read from environment variables:
            # - LLM_HOST for base_url (falls back to default DashScope URL)
            # - DASHSCOPE_API_KEY or OPENAI_API_KEY for api_key
        )

        blueprint = generator.generate_blueprint(
            task_description=task_description,
            codebase_context=codebase_context,
        )

        print(f"✅ Blueprint generated successfully!")
        print()
        print(blueprint.summary())
        print()

    except Exception as e:
        print(f"❌ Failed to generate blueprint: {e}")
        import traceback
        traceback.print_exc()
        return 1

    # Step 2: Show approval UI
    print("🖼️  Step 2: Launching approval UI in browser...")
    print()
    print("The blueprint will open in your browser.")
    print("Review the architecture and click 'Approve' or 'Reject'.")
    print()

    try:
        server = ApprovalServer(blueprint, port=8765)
        decision = server.start_and_wait()

        print()
        print(f"✅ Decision received: {'APPROVED' if decision.approved else 'REJECTED'}")
        print()

        if decision.approved:
            print("🎉 Blueprint approved! In a full implementation, we would now:")
            print("   1. Generate code for each component")
            print("   2. Create/modify files as specified")
            print("   3. Run tests and verification")
            print()
            print("For this MVP demo, we're stopping here.")
            print("The blueprint is ready for code generation!")
        else:
            print("❌ Blueprint rejected. In a full implementation, we would:")
            print("   1. Ask user for specific feedback")
            print("   2. Refine the blueprint using feedback")
            print("   3. Show updated blueprint for re-approval")
            print()
            print("For this MVP demo, we're stopping here.")

    except Exception as e:
        print(f"❌ Approval UI failed: {e}")
        import traceback
        traceback.print_exc()
        return 1

    print()
    print("=" * 80)
    print("✅ ClarAIty Generate Mode Demo Complete!")
    print("=" * 80)
    print()
    print("What we demonstrated:")
    print("  1. ✅ Task description → LLM generates architecture blueprint")
    print("  2. ✅ Blueprint contains: components, decisions, file actions, relationships")
    print("  3. ✅ Interactive approval UI in browser")
    print("  4. ✅ User can approve/reject BEFORE any code is generated")
    print()
    print("This solves the 'shooting in the dark' problem!")
    print("User sees the PLAN before execution begins.")
    print()

    return 0


if __name__ == "__main__":
    sys.exit(main())
