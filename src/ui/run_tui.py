#!/usr/bin/env python3
"""
Run the Textual TUI for the AI Coding Agent.

This is the entry point for launching the new Textual-based TUI.

Usage:
    # Run with demo mode (no real agent)
    python -m src.ui.run_tui --demo

    # Run with real agent
    python -m src.ui.run_tui

    # Run with specific model
    python -m src.ui.run_tui --model claude-3-opus
"""

import argparse
import asyncio
import sys
from pathlib import Path

# Add project root to path
project_root = Path(__file__).parent.parent.parent
sys.path.insert(0, str(project_root))


def main():
    """Main entry point."""
    parser = argparse.ArgumentParser(
        description="AI Coding Agent TUI",
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    parser.add_argument(
        "--demo",
        action="store_true",
        help="Run in demo mode (no real agent)",
    )
    parser.add_argument(
        "--model",
        type=str,
        default="claude-3-opus",
        help="Model name to display in status bar",
    )
    parser.add_argument(
        "--header",
        action="store_true",
        help="Show header bar",
    )

    args = parser.parse_args()

    if args.demo:
        run_demo_mode(args.model, args.header)
    else:
        run_agent_mode(args.model, args.header)


def run_demo_mode(model_name: str, show_header: bool):
    """Run TUI in demo mode with simulated responses."""
    from src.ui.app import CodingAgentApp
    from src.ui.agent_adapter import demo_stream_handler

    print("Starting TUI in demo mode...")
    print("This demonstrates the UI without a real agent.")
    print()

    app = CodingAgentApp(
        stream_handler=demo_stream_handler,
        model_name=f"{model_name} (demo)",
        show_header=show_header,
    )
    try:
        app.run()
    except KeyboardInterrupt:
        # Gracefully handle Ctrl+C
        print("\nExiting...")


def run_agent_mode(model_name: str, show_header: bool):
    """Run TUI with the real coding agent."""
    try:
        from src.core.agent import CodingAgent
        from src.ui.app import CodingAgentApp
        from src.ui.agent_adapter import create_stream_handler

        print("Initializing AI Coding Agent...")

        # Initialize the agent
        agent = CodingAgent()

        # Create stream handler
        stream_handler = create_stream_handler(agent)

        # Get model name from agent if available
        if hasattr(agent, 'model_name'):
            model_name = agent.model_name

        print(f"Using model: {model_name}")
        print("Starting TUI...")
        print()

        app = CodingAgentApp(
            stream_handler=stream_handler,
            model_name=model_name,
            show_header=show_header,
        )
        try:
            app.run()
        except KeyboardInterrupt:
            # Gracefully handle Ctrl+C
            print("\nExiting...")

    except ImportError as e:
        print(f"Error: Could not import agent module: {e}")
        print("Try running with --demo flag to test the TUI without an agent.")
        sys.exit(1)
    except Exception as e:
        print(f"Error initializing agent: {e}")
        print("Try running with --demo flag to test the TUI without an agent.")
        sys.exit(1)


if __name__ == "__main__":
    main()
