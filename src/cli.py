"""Command-line interface for the AI coding agent (TUI-only)."""

import asyncio
import os
import sys

# CRITICAL: Remove TERM on Windows BEFORE importing prompt_toolkit
# This prevents prompt_toolkit from thinking we're in a Unix terminal
if sys.platform == 'win32' and 'TERM' in os.environ:
    del os.environ['TERM']

# CRITICAL: Set Windows event loop policy for proper async I/O
# This must be done before any asyncio operations
if sys.platform == 'win32':
    asyncio.set_event_loop_policy(asyncio.WindowsProactorEventLoopPolicy())

import argparse
from pathlib import Path
from typing import TYPE_CHECKING, Optional

if TYPE_CHECKING:
    from src.llm.config_loader import LLMConfigData

# CRITICAL: Load .env BEFORE any imports that initialize observability
# Langfuse/OTEL SDK reads env vars at import time
from dotenv import load_dotenv

load_dotenv()

# CRITICAL: Import platform module early to activate global print() override
# This prevents Windows encoding crashes throughout the entire codebase
from rich.console import Console

import src.platform  # noqa: F401 (unused import - side effect only)
from src.core import CodingAgent
from src.execution.controller import LongRunningController
from src.ui.app import CodingAgentApp

console = Console()


def chat_mode(
    agent: CodingAgent | None = None,
    controller: LongRunningController | None = None,
    log_level: str | None = None,
    llm_config: Optional["LLMConfigData"] = None,
) -> None:
    """Interactive chat mode with Textual TUI and async streaming.

    Uses Textual framework for rich UI with code blocks, tool cards, and streaming.
    The agent's stream_response() method yields typed UIEvents that the TUI renders.

    When agent is None (LLM not yet configured), launches TUI in setup mode
    and auto-presents the configuration wizard.

    Args:
        agent: CodingAgent instance, or None for setup-only mode
        controller: Optional LongRunningController for checkpoint functionality
        log_level: Optional CLI log level override
        llm_config: Optional LLMConfigData for post-wizard agent initialization
    """
    try:
        # Configure logging - all logs go to JSONL file only, no console output
        from src.observability.logging_config import configure_logging, install_asyncio_handler
        configure_logging(mode="tui", log_level=log_level)

        import uuid
        from datetime import datetime

        from src.session.persistence.writer import SessionWriter
        from src.session.store.memory_store import MessageStore

        if agent:
            # Full mode: agent already has session_id + message_store from from_config()
            session_id = agent.session_id
            store = agent.message_store
        else:
            # Setup mode: create session scaffolding for TUI (agent will be wired later)
            session_id = f"session-{datetime.now().strftime('%Y%m%d-%H%M%S')}-{uuid.uuid4().hex[:8]}"
            store = MessageStore()

        # Prepare session writer (directory created on first write, not now)
        sessions_dir = Path(".clarity/sessions")
        session_dir = sessions_dir / session_id
        jsonl_path = session_dir / "session.jsonl"
        writer = SessionWriter(file_path=jsonl_path)

        # Create and run Textual app (agent=None triggers setup mode)
        app = CodingAgentApp(
            agent=agent,
            show_header=False,
        )

        # Pass llm_config so the app can init agent after wizard completes
        app._pending_llm_config = llm_config

        # Bind store and writer to app
        app.bind_store(store, session_id=session_id)
        app.set_session_writer(writer)

        if agent:
            # Wire up render meta registry for approval policy hints
            app.set_render_meta_registry(agent.memory.render_meta)

        app.run()

        # Session is auto-saved - no need to show path to users (implementation detail)

    except Exception as e:
        console.print(f"[red]Failed to launch TUI: {type(e).__name__}: {e}[/red]")
        sys.exit(1)


def main() -> None:
    """Main CLI entry point - launches TUI."""
    parser = argparse.ArgumentParser(
        description="AI Coding Agent - Optimized for small open-source LLMs"
    )

    parser.add_argument(
        "--model",
        default=None,
        help="Model name (from .env: LLM_MODEL, or .clarity/config.yaml)"
    )

    parser.add_argument(
        "--backend",
        default=None,
        choices=["ollama", "openai"],
        help="LLM backend (from .env: LLM_BACKEND, or .clarity/config.yaml)"
    )

    parser.add_argument(
        "--url",
        default=None,
        help="Backend API URL (from .env: LLM_HOST, or .clarity/config.yaml)"
    )

    parser.add_argument(
        "--context",
        type=int,
        default=None,
        help="Context window size (from .env: MAX_CONTEXT_TOKENS, or .clarity/config.yaml)"
    )

    parser.add_argument(
        "--api-key",
        default=None,
        help="API key for OpenAI-compatible backends (optional, can use env var)"
    )

    parser.add_argument(
        "--api-key-env",
        default=None,
        help="Environment variable name for API key (default: OPENAI_API_KEY)"
    )

    # LLM generation parameters
    parser.add_argument(
        "--temperature",
        type=float,
        default=None,
        help="LLM temperature (from .env: LLM_TEMPERATURE, or .clarity/config.yaml)"
    )

    parser.add_argument(
        "--max-tokens",
        type=int,
        default=None,
        help="Max output tokens (from .env: LLM_MAX_TOKENS, or .clarity/config.yaml)"
    )

    parser.add_argument(
        "--top-p",
        type=float,
        default=None,
        help="Top-p sampling (from .env: LLM_TOP_P, or .clarity/config.yaml)"
    )

    parser.add_argument(
        "--permission",
        default=os.environ.get("PERMISSION_MODE", "normal"),
        choices=["plan", "normal", "auto"],
        help="Permission mode (from .env: PERMISSION_MODE, or normal by default)"
    )

    parser.add_argument(
        "--log-level",
        default=None,
        choices=["debug", "info", "warning", "error", "critical"],
        help="Override log level (overrides .clarity/config.yaml, overridden by LOG_LEVEL env var)"
    )

    args = parser.parse_args()

    # ---------------------------------------------------------------
    # Unified config: YAML file + env vars + CLI args (layered)
    # ---------------------------------------------------------------
    from src.llm.config_loader import load_llm_config, resolve_llm_config

    # Secure the .clarity workspace directory permissions at startup
    from src.security.file_permissions import secure_clarity_workspace
    clarity_dir = Path(".clarity")
    if clarity_dir.exists():
        secure_clarity_workspace(clarity_dir)

    llm_config = load_llm_config()

    # Env vars layer (reads from .env / environment)
    env_vars = {
        "model": os.environ.get("LLM_MODEL"),
        "backend": os.environ.get("LLM_BACKEND"),
        "url": os.environ.get("LLM_HOST"),
        "context_window": os.environ.get("MAX_CONTEXT_TOKENS"),
        "temperature": os.environ.get("LLM_TEMPERATURE"),
        "max_tokens": os.environ.get("LLM_MAX_TOKENS"),
        "top_p": os.environ.get("LLM_TOP_P"),
        "api_key_env": os.environ.get("API_KEY_ENV"),
    }

    # CLI args layer (None means "not passed")
    cli_args = {
        "model": args.model,
        "backend": args.backend,
        "url": args.url,
        "context_window": str(args.context) if args.context is not None else None,
        "temperature": str(args.temperature) if args.temperature is not None else None,
        "max_tokens": str(args.max_tokens) if args.max_tokens is not None else None,
        "top_p": str(args.top_p) if args.top_p is not None else None,
        "api_key_env": args.api_key_env,
    }

    llm_config = resolve_llm_config(env_vars, cli_args, llm_config)

    # Check if LLM configuration is complete
    llm_configured = bool(llm_config.model and llm_config.backend_type and llm_config.base_url)

    if not llm_configured:
        # Launch TUI without agent -- it will auto-show the config wizard
        console.print("[yellow]No LLM configured. Launching setup wizard...[/yellow]")
        cli_log_level = args.log_level
        from src.observability.logging_config import configure_logging
        configure_logging(mode="tui", log_level=cli_log_level)
        chat_mode(agent=None, controller=None, log_level=cli_log_level, llm_config=llm_config)
        return

    # Initialize agent
    console.print("\n[cyan]Initializing AI Coding Agent...[/cyan]")
    console.print(f"Model: {llm_config.model}")
    console.print(f"Backend: {llm_config.backend_type}")
    console.print(f"URL: {llm_config.base_url}")

    # Resolve API key: CLI flag > keyring > env var
    # (llm_config.api_key is already populated from keyring/env by load_llm_config)
    resolved_api_key = args.api_key or llm_config.api_key

    try:
        agent = CodingAgent.from_config(
            llm_config,
            api_key=resolved_api_key,
            permission_mode=args.permission,
        )

        # Check if backend is available
        if not agent.llm.is_available():
            console.print(f"[red]Error: {llm_config.backend_type} backend not available at {llm_config.base_url}[/red]")
            console.print("[yellow]This is usually caused by:[/yellow]")
            console.print("  - Incorrect API key")
            console.print("  - Wrong base URL")
            console.print("  - Network/firewall issues")
            console.print("\n[cyan]Opening LLM configuration wizard...[/cyan]\n")

            # Configure logging for TUI mode
            cli_log_level = args.log_level
            from src.observability.logging_config import configure_logging
            configure_logging(mode="tui", log_level=cli_log_level)

            # Launch TUI with config wizard (agent will be None to trigger wizard)
            chat_mode(agent=None, controller=None, log_level=cli_log_level, llm_config=llm_config)
            return

        console.print("[green]Agent initialized successfully![/green]\n")

        # Initialize Long Running Controller for checkpoints
        controller = LongRunningController(
            agent=agent,
            project_dir=".",
            max_checkpoints=10
        )

        # Wire controller to checkpoint tool
        for tool in agent.tool_executor.tools.values():
            if tool.name == "create_checkpoint":
                tool.set_controller(controller)
                break

        # Configure logging
        cli_log_level = args.log_level
        from src.observability.logging_config import configure_logging
        configure_logging(mode="tui", log_level=cli_log_level)

        # Always launch TUI
        chat_mode(agent, controller, log_level=cli_log_level, llm_config=llm_config)

    except Exception as e:
        console.print(f"[red]Failed to initialize agent: {e}[/red]")
        sys.exit(1)


if __name__ == "__main__":
    main()
