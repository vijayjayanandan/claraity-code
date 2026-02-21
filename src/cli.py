"""Command-line interface for the AI coding agent."""

import sys
import os
import asyncio

# CRITICAL: Remove TERM on Windows BEFORE importing prompt_toolkit
# This prevents prompt_toolkit from thinking we're in a Unix terminal
if sys.platform == 'win32' and 'TERM' in os.environ:
    del os.environ['TERM']

# CRITICAL: Set Windows event loop policy for proper async I/O
# This must be done before any asyncio operations
if sys.platform == 'win32':
    asyncio.set_event_loop_policy(asyncio.WindowsProactorEventLoopPolicy())

from pathlib import Path
from typing import Optional
import argparse
import logging

# CRITICAL: Load .env BEFORE any imports that initialize observability
# Langfuse/OTEL SDK reads env vars at import time
from dotenv import load_dotenv
load_dotenv()

# CRITICAL: Import platform module early to activate global print() override
# This prevents Windows encoding crashes throughout the entire codebase
import src.platform  # noqa: F401 (unused import - side effect only)

from rich.console import Console
from rich.markdown import Markdown
from rich.panel import Panel
from rich.prompt import Prompt
from rich.status import Status

from prompt_toolkit import PromptSession
from prompt_toolkit.key_binding import KeyBindings
from prompt_toolkit.formatted_text import HTML

from src.core import CodingAgent
from src.execution.controller import LongRunningController
from src.ui.app import CodingAgentApp

# Logging is configured lazily in chat_mode() / simple_chat_mode()
# via configure_logging() which loads .clarity/config.yaml + env overrides.
# The --log-level CLI flag is passed through as an override.
_logging_configured = False


console = Console()


def chat_mode(
    agent: Optional[CodingAgent] = None,
    controller: Optional[LongRunningController] = None,
    log_level: Optional[str] = None,
    llm_config: Optional["LLMConfigData"] = None,
) -> None:
    """Interactive chat mode with professional Textual TUI and async streaming.

    Uses Textual framework for rich UI with code blocks, tool cards, and streaming.
    The agent's stream_response() method yields typed UIEvents that the TUI renders.
    Falls back to simple mode if TUI fails.

    When agent is None (LLM not yet configured), launches TUI in setup mode
    and auto-presents the configuration wizard.

    Phase 6: Integrates MessageStore for session persistence to JSONL.

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

        # Phase 6: Initialize MessageStore and SessionWriter for persistence
        from src.session.store.memory_store import MessageStore
        from src.session.persistence.writer import SessionWriter
        import uuid
        from datetime import datetime

        # Prepare session path (directory will be created on first message write)
        session_id = f"session-{datetime.now().strftime('%Y%m%d-%H%M%S')}-{uuid.uuid4().hex[:8]}"
        sessions_dir = Path(".clarity/sessions")
        session_dir = sessions_dir / session_id
        # DO NOT create directory yet - SessionWriter will create it on first write
        jsonl_path = session_dir / "session.jsonl"

        # Initialize store (writer will be opened by app in its event loop)
        store = MessageStore()
        writer = SessionWriter(file_path=jsonl_path)

        if agent:
            # Full mode: agent is ready
            # Set session ID on agent for plan mode and other session-scoped features
            agent.set_session_id(session_id, is_new_session=True)

            # Link MemoryManager to MessageStore for unified data flow
            agent.memory.set_message_store(store, session_id)

        # Create and run Textual app (agent=None triggers setup mode)
        app = CodingAgentApp(
            agent=agent,
            show_header=False,
        )

        # Pass llm_config so the app can init agent after wizard completes
        app._pending_llm_config = llm_config

        # Phase 6: Bind store and writer to app
        app.bind_store(store, session_id=session_id)
        app.set_session_writer(writer)

        if agent:
            # Wire up render meta registry for approval policy hints
            app.set_render_meta_registry(agent.memory.render_meta)

        app.run()

        # Session is auto-saved - no need to show path to users (implementation detail)

    except Exception as e:
        if agent:
            # Fallback to simple mode only when agent exists
            console.print(f"[dim]TUI unavailable: {type(e).__name__}: {e}[/dim]")
            console.print(f"[dim]Falling back to simple chat mode...[/dim]")
            simple_chat_mode(agent, controller, log_level=log_level)
        else:
            console.print(f"[red]Failed to launch setup wizard: {type(e).__name__}: {e}[/red]")
            sys.exit(1)


def simple_chat_mode(agent: CodingAgent, controller: Optional[LongRunningController] = None, log_level: Optional[str] = None) -> None:
    """Simple interactive chat mode (fallback).

    Args:
        agent: CodingAgent instance
        controller: Optional LongRunningController for checkpoint functionality
        log_level: Optional CLI log level override
    """
    # Configure logging - all logs go to JSONL file only, no console output
    from src.observability.logging_config import configure_logging
    configure_logging(mode="cli", log_level=log_level)

    console.print(Panel.fit(
        "[bold cyan]AI Coding Agent - Interactive Mode[/bold cyan]\n"
        f"Model: {agent.model_name}\n"
        f"Context: {agent.context_window} tokens\n"
        f"Current mode: {agent.get_permission_mode().upper()}\n"
        "[dim]Press Alt+M to toggle mode | Type ? for quick reference | Type 'exit' to quit[/dim]",
        border_style="cyan"
    ))

    # Setup key bindings for Alt+M
    kb = KeyBindings()

    @kb.add('escape', 'm')  # Alt+M (escape sequence for Alt key)
    def _(event):
        """Toggle permission mode with Alt+M (silent toggle)"""
        current_mode = agent.get_permission_mode()

        # Cycle through modes silently
        mode_cycle = {
            "plan": "normal",
            "normal": "auto",
            "auto": "plan"
        }

        next_mode = mode_cycle.get(current_mode, "normal")
        agent.set_permission_mode(next_mode)

        # Update the bottom toolbar without printing
        event.app.invalidate()

    # Function to generate bottom toolbar showing current mode
    # Only show for PLAN and AUTO modes (not NORMAL)
    # Style: subtle floating text like Claude Code (no background bar)
    def bottom_toolbar():
        mode = agent.get_permission_mode().lower()

        # Don't show toolbar for NORMAL mode
        if mode == "normal":
            return None

        # Subtle, muted style - just text, no loud colors
        if mode == "plan":
            return 'plan mode on (alt+m to cycle)'
        else:  # auto
            return 'auto accept on (alt+m to cycle)'

    # Style to remove toolbar background (make it transparent like Claude Code)
    from prompt_toolkit.styles import Style
    style = Style.from_dict({
        'bottom-toolbar': 'noreverse',
    })

    # Create prompt session with key bindings and styled toolbar
    session = PromptSession(
        key_bindings=kb,
        bottom_toolbar=bottom_toolbar,
        style=style
    )

    director_pending = False  # True when user typed /director with no task

    while True:
        try:
            # Simple prompt - mode is shown in status bar only
            user_input = session.prompt('> ')

            if not user_input.strip():
                continue

            # Handle commands
            if user_input.lower() in ["exit", "quit", "q"]:
                # Prompt to save checkpoint before exiting
                if controller:
                    from rich.prompt import Confirm
                    save = Confirm.ask(
                        "Save checkpoint before exiting?",
                        default=True
                    )
                    if save:
                        description = Prompt.ask(
                            "[cyan]Description[/cyan]",
                            default="Session ended"
                        )
                        controller.create_checkpoint(description=description)
                        console.print("[green]Checkpoint saved[/green]")

                agent.shutdown()
                console.print("[yellow]Goodbye![/yellow]")
                break

            if user_input.lower() == "help":
                show_help()
                continue

            if user_input.lower() == "stats":
                show_stats(agent)
                continue

            # Session management commands
            if user_input.lower().startswith("session-save") or user_input.lower().startswith("save"):
                save_session_command(agent, user_input)
                continue

            if user_input.lower() == "session-list" or user_input.lower() == "sessions":
                list_sessions_command(agent)
                continue

            if user_input.lower().startswith("session-load"):
                load_session_command(agent, user_input)
                continue

            if user_input.lower().startswith("session-delete"):
                delete_session_command(agent, user_input)
                continue

            if user_input.lower().startswith("session-info"):
                session_info_command(agent, user_input)
                continue

            if user_input.lower() == "clear":
                agent.clear_memory()
                console.print("[green]Memory cleared![/green]")
                continue

            # Memory management commands
            if user_input.lower() == "memory":
                show_file_memories(agent)
                continue

            if user_input.lower() == "memory-init":
                init_project_memory(agent)
                continue

            if user_input.lower().startswith("memory-add"):
                parts = user_input.split(maxsplit=1)
                if len(parts) < 2:
                    console.print("[yellow]Usage: memory-add <text>[/yellow]")
                    continue
                add_memory(agent, parts[1])
                continue

            if user_input.lower() == "memory-reload":
                reload_memories(agent)
                continue

            # Quick reference shortcut
            if user_input == "?":
                show_quick_reference(agent)
                continue

            # Permission mode commands
            if user_input.lower().startswith("/mode"):
                parts = user_input.lower().split()

                if len(parts) == 1:
                    # Just "/mode" - toggle through modes
                    toggle_permission_mode(agent)
                elif len(parts) == 2:
                    # "/mode p/n/a" - set specific mode
                    mode_arg = parts[1]
                    mode_map = {
                        'p': 'plan',
                        'n': 'normal',
                        'a': 'auto'
                    }

                    if mode_arg in mode_map:
                        set_permission_mode(agent, mode_map[mode_arg])
                    else:
                        console.print("[yellow]Invalid mode argument. Use: /mode p, /mode n, or /mode a[/yellow]")
                        console.print("[dim]Or type ? for quick reference[/dim]")
                else:
                    console.print("[yellow]Usage: /mode [p|n|a][/yellow]")
                    console.print("[dim]  /mode    - Toggle mode[/dim]")
                    console.print("[dim]  /mode p  - Set to Plan mode[/dim]")
                    console.print("[dim]  /mode n  - Set to Normal mode[/dim]")
                    console.print("[dim]  /mode a  - Set to Auto mode[/dim]")
                continue

            # Director mode commands
            if user_input.lower().startswith("/director") and not user_input.lower().startswith("/director-"):
                task = user_input[len("/director"):].strip()
                if not task:
                    # Bare /director -- wait for next message as task
                    director_pending = True
                    console.print("[green]Director mode ready. Type your task to begin.[/green]")
                    continue
                agent.director_adapter.start(task)
                director_pending = False
                console.print(f"[green]Director mode activated - UNDERSTAND phase[/green]")
                console.print(f"[dim]Task: {task}[/dim]")
                user_input = task  # Send task as the user message (fall through)

            elif user_input.lower() == "/director-reset":
                agent.director_adapter.reset()
                director_pending = False
                console.print("[green]Director mode reset[/green]")
                continue

            # Handle pending director activation -- next message becomes the task
            if director_pending and not user_input.startswith("/"):
                agent.director_adapter.start(user_input)
                director_pending = False
                console.print(f"[green]Director mode activated - UNDERSTAND phase[/green]")
                console.print(f"[dim]Task: {user_input}[/dim]")
                # Fall through to send as message

            # Hooks commands
            if user_input.lower() in ["hooks", "hooks-status"]:
                show_hooks_status(agent)
                continue

            if user_input.lower() == "hooks-reload":
                reload_hooks(agent)
                continue

            if user_input.lower() == "hooks-examples":
                list_hook_examples()
                continue

            # ClarAIty commands
            if user_input.lower() == "clarity-status":
                show_clarity_status(agent)
                continue

            if user_input.lower() == "clarity-scan":
                trigger_clarity_scan(agent)
                continue

            if user_input.lower() == "clarity-components":
                list_clarity_components(agent)
                continue

            if user_input.lower() == "clarity-stats":
                show_clarity_stats(agent)
                continue

            if user_input.lower() == "clarity-ui":
                launch_clarity_ui(agent)
                continue

            # Checkpoint commands
            if user_input.lower().startswith("checkpoint-save") or user_input.lower().startswith("checkpoint-create"):
                create_checkpoint_command(controller, user_input)
                continue

            if user_input.lower() == "checkpoint-list" or user_input.lower() == "checkpoints":
                list_checkpoints_command(controller)
                continue

            if user_input.lower().startswith("checkpoint-restore"):
                restore_checkpoint_command(controller, user_input)
                continue

            if user_input.lower() == "checkpoint-clear":
                clear_checkpoints_command(controller)
                continue

            # Process with agent
            console.print()  # Single newline for spacing
            console.print("[dim]Agent[/dim]")

            # Create status indicator for thinking phase
            status = Status("Thinking...", console=console, spinner="dots")

            def stop_status():
                """Callback to stop status when streaming starts."""
                status.stop()

            # Start thinking indicator and chat
            status.start()
            response = agent.chat(user_input, stream=True, on_stream_start=stop_status)
            status.stop()  # Ensure status is stopped if streaming never starts

            # Note: Response content is already printed during streaming
            # No need to print again here
            console.print()  # Extra spacing after response

        except KeyboardInterrupt:
            console.print()  # New line after ^C

            # Prompt to save checkpoint before exiting
            if controller:
                from rich.prompt import Confirm
                save = Confirm.ask(
                    "Save checkpoint before exiting?",
                    default=True
                )
                if save:
                    description = Prompt.ask(
                        "[cyan]Description[/cyan]",
                        default="Session interrupted"
                    )
                    controller.create_checkpoint(description=description)
                    console.print("[green]Checkpoint saved[/green]")

            console.print("[yellow]Goodbye![/yellow]")
            break
        except Exception as e:
            console.print(f"[red]Error: {e}[/red]")


def show_file_memories(agent: CodingAgent) -> None:
    """Show current file-based memories."""
    file_memory = agent.memory.file_memory_content

    if not file_memory:
        console.print("[yellow]No file memories loaded.[/yellow]")
        console.print("[dim]Run 'memory-init' to create a project memory file.[/dim]")
        return

    console.print("\n[bold cyan]File Memories:[/bold cyan]")
    console.print(Panel(
        file_memory[:1000] + ("..." if len(file_memory) > 1000 else ""),
        title="Memory Content (first 1000 chars)",
        border_style="cyan"
    ))
    console.print(f"\n[dim]Total size: {len(file_memory)} characters[/dim]")
    console.print(f"[dim]Loaded files: {len(agent.memory.file_loader.loaded_files)}[/dim]")


def init_project_memory(agent: CodingAgent) -> None:
    """Initialize project memory template."""
    try:
        path = agent.memory.init_project_memory()
        console.print(f"[green]✓ Created project memory template: {path}[/green]")
        console.print("[dim]Edit .opencodeagent/memory.md to customize for your project.[/dim]")
    except FileExistsError:
        console.print("[yellow]Project memory file already exists at .opencodeagent/memory.md[/yellow]")
        console.print("[dim]Run 'memory-reload' to refresh if you've edited it.[/dim]")
    except Exception as e:
        console.print(f"[red]Error creating project memory: {e}[/red]")


def add_memory(agent: CodingAgent, text: str, location: str = "project") -> None:
    """Quick add memory to file."""
    try:
        path = agent.memory.quick_add_memory(text, location=location)
        console.print(f"[green]✓ Added memory to: {path}[/green]")
        console.print(f"[dim]Text: {text[:80]}{'...' if len(text) > 80 else ''}[/dim]")
    except Exception as e:
        console.print(f"[red]Error adding memory: {e}[/red]")


def reload_memories(agent: CodingAgent) -> None:
    """Reload file-based memories."""
    try:
        content = agent.memory.reload_file_memories()
        if content:
            console.print(f"[green]✓ Reloaded file memories ({len(content)} chars)[/green]")
            console.print(f"[dim]Loaded {len(agent.memory.file_loader.loaded_files)} files[/dim]")
        else:
            console.print("[yellow]No file memories found.[/yellow]")
    except Exception as e:
        console.print(f"[red]Error reloading memories: {e}[/red]")


def show_permission_mode(agent: CodingAgent) -> None:
    """Show current permission mode."""
    try:
        current_mode = agent.get_permission_mode()
        description = agent.get_permission_mode_description()

        console.print(f"\n[bold cyan]Current Permission Mode:[/bold cyan]")
        console.print(Panel(
            description,
            title=f"Mode: {current_mode.upper()}",
            border_style="cyan"
        ))

        console.print("\n[dim]Use 'permission-set <mode>' to change mode[/dim]")
        console.print("[dim]Valid modes: plan, normal, auto[/dim]")

    except Exception as e:
        console.print(f"[red]Error getting permission mode: {e}[/red]")


def set_permission_mode(agent: CodingAgent, mode: str) -> None:
    """Set permission mode."""
    try:
        old_mode = agent.get_permission_mode()
        agent.set_permission_mode(mode)
        new_mode = agent.get_permission_mode()

        console.print(f"[green]✓ Permission mode changed: {old_mode} → {new_mode}[/green]")

        # Show description of new mode
        description = agent.get_permission_mode_description()
        console.print(f"\n{description}\n")

    except ValueError as e:
        console.print(f"[red]Invalid permission mode: {e}[/red]")
        console.print("[yellow]Valid modes: plan, normal, auto[/yellow]")
    except Exception as e:
        console.print(f"[red]Error setting permission mode: {e}[/red]")


def toggle_permission_mode(agent: CodingAgent) -> None:
    """Toggle permission mode (like Shift+Tab in Claude Code).

    Cycles through: plan → normal → auto → plan
    """
    try:
        current_mode = agent.get_permission_mode()

        # Cycle through modes
        mode_cycle = {
            "plan": "normal",
            "normal": "auto",
            "auto": "plan"
        }

        next_mode = mode_cycle.get(current_mode, "normal")
        agent.set_permission_mode(next_mode)

        # Show quick status with marker
        mode_marker = {
            "plan": "[PLAN]",
            "normal": "[NORM]",
            "auto": "[AUTO]"
        }

        marker = mode_marker.get(next_mode, "")
        console.print(f"\n{marker} [bold green]Permission mode: {current_mode} → {next_mode}[/bold green]")

        # Show brief description
        descriptions = {
            "plan": "Always ask for approval (review mode)",
            "normal": "Ask only for high-risk operations (balanced)",
            "auto": "Never ask for approval (fully autonomous)"
        }
        console.print(f"[dim]{descriptions.get(next_mode, '')}[/dim]\n")

    except Exception as e:
        console.print(f"[red]Error toggling permission mode: {e}[/red]")


def show_quick_reference(agent: CodingAgent) -> None:
    """Show quick reference guide (triggered by ? shortcut)."""
    from rich.table import Table

    current_mode = agent.get_permission_mode().upper()

    # Create quick reference panel
    mode_color = 'yellow' if current_mode == 'PLAN' else 'cyan' if current_mode == 'NORMAL' else 'green'
    help_text = f"""[bold cyan]SHORTCUTS:[/bold cyan]
  ?                  Show this quick reference

[bold cyan]MODE COMMANDS:[/bold cyan]
  /mode              Toggle permission mode (plan → normal → auto)
  /mode p            Set to Plan mode (always ask approval)
  /mode n            Set to Normal mode (balanced - default)
  /mode a            Set to Auto mode (fully autonomous)

[bold cyan]OTHER COMMANDS:[/bold cyan]
  save [name]        Save current session
  sessions           List all saved sessions
  help               Show detailed help
  exit               Quit the application

[bold cyan]CURRENT MODE:[/bold cyan] [bold {mode_color}]{current_mode}[/bold {mode_color}]
  Shown in prompt: [{current_mode}] You>

[dim]Note: Mode is shown in the prompt with color coding
  Yellow = PLAN, Cyan = NORMAL, Green = AUTO[/dim]
"""

    console.print(Panel(
        help_text,
        title="Quick Reference",
        border_style="cyan",
        padding=(1, 2)
    ))


def save_session_command(agent: CodingAgent, user_input: str) -> None:
    """Enhanced session save command with tags and description."""
    from rich.prompt import Confirm

    parts = user_input.split(maxsplit=1)
    session_name = parts[1] if len(parts) > 1 else None

    # If no name provided, ask for one
    if not session_name:
        session_name = Prompt.ask(
            "[cyan]Session name[/cyan] (optional, press Enter to skip)",
            default=""
        )
        if not session_name:
            session_name = None

    # Ask for description
    description = Prompt.ask(
        "[cyan]Task description[/cyan] (what were you working on?)",
        default="General coding session"
    )

    # Ask for tags
    tags_input = Prompt.ask(
        "[cyan]Tags[/cyan] (comma-separated, e.g., 'feature,auth,backend')",
        default=""
    )
    tags = [t.strip() for t in tags_input.split(",") if t.strip()]

    try:
        session_id = agent.memory.save_session(
            session_name=session_name,
            task_description=description,
            tags=tags,
            permission_mode=agent.get_permission_mode()
        )

        console.print(f"\n[green]✓ Session saved successfully![/green]")
        console.print(f"[dim]Session ID: {session_id[:8]}[/dim]")
        if session_name:
            console.print(f"[dim]Name: {session_name}[/dim]")
        console.print(f"[dim]Description: {description}[/dim]")
        if tags:
            console.print(f"[dim]Tags: {', '.join(tags)}[/dim]")

        # Show stats
        stats = agent.memory.get_statistics()
        console.print(f"\n[cyan]Saved:[/cyan]")
        console.print(f"  • {stats['working_memory']['messages']} messages")
        console.print(f"  • {stats['episodic_memory']['total_turns']} conversation turns")
        console.print(f"  • {stats['session_duration_minutes']:.1f} minutes duration")

    except Exception as e:
        console.print(f"[red]Error saving session: {e}[/red]")


def list_sessions_command(agent: CodingAgent) -> None:
    """List all saved sessions."""
    from rich.table import Table
    from src.core.session_manager import SessionManager

    try:
        sessions_dir = agent.memory.persist_directory / "sessions"
        session_manager = SessionManager(sessions_dir=sessions_dir)

        sessions = session_manager.list_sessions()

        if not sessions:
            console.print("[yellow]No saved sessions found.[/yellow]")
            console.print("[dim]Use 'session-save' or 'save' to save your first session.[/dim]")
            return

        # Create table
        table = Table(title=f"Saved Sessions ({len(sessions)} total)", show_header=True)
        table.add_column("ID", style="cyan", width=10)
        table.add_column("Name", style="green", width=20)
        table.add_column("Description", style="white", width=25)
        table.add_column("Mode", style="magenta", width=8)
        table.add_column("Messages", justify="right", style="blue", width=8)
        table.add_column("Duration", justify="right", style="magenta", width=10)
        table.add_column("Updated", style="yellow", width=16)
        table.add_column("Tags", style="dim", width=15)

        for session in sessions:
            # Format duration
            duration = f"{session.duration_minutes:.0f}m"

            # Format updated time (relative)
            from datetime import datetime
            now = datetime.now()
            updated = session.updated_datetime
            delta = now - updated

            if delta.days > 0:
                updated_str = f"{delta.days}d ago"
            elif delta.seconds > 3600:
                updated_str = f"{delta.seconds // 3600}h ago"
            else:
                updated_str = f"{delta.seconds // 60}m ago"

            # Format tags
            tags_str = ", ".join(session.tags[:3]) if session.tags else ""
            if len(session.tags) > 3:
                tags_str += "..."

            # Get permission mode (with backward compatibility)
            mode = getattr(session, 'permission_mode', 'normal').upper()

            table.add_row(
                session.short_id,
                session.name or "[dim]unnamed[/dim]",
                session.task_description[:25] + ("..." if len(session.task_description) > 25 else ""),
                mode,
                str(session.message_count),
                duration,
                updated_str,
                tags_str
            )

        console.print()
        console.print(table)
        console.print()
        console.print("[dim]Use 'session-load <id>' to resume a session[/dim]")
        console.print("[dim]Use 'session-info <id>' for details[/dim]")

    except Exception as e:
        console.print(f"[red]Error listing sessions: {e}[/red]")


def load_session_command(agent: CodingAgent, user_input: str) -> None:
    """Load a saved session."""
    from rich.prompt import Confirm

    parts = user_input.split(maxsplit=1)

    if len(parts) < 2:
        console.print("[yellow]Usage: session-load <session-id|name>[/yellow]")
        console.print("[dim]Example: session-load abc12345[/dim]")
        console.print("[dim]Use 'session-list' to see available sessions[/dim]")
        return

    session_id = parts[1].strip()

    # Confirm before loading (will clear current memory)
    if agent.memory.working_memory.messages:
        confirm = Confirm.ask(
            f"[yellow][WARN] Loading will clear current conversation. Continue?[/yellow]",
            default=False
        )
        if not confirm:
            console.print("[dim]Load cancelled.[/dim]")
            return

    try:
        # Get session info first
        from src.core.session_manager import SessionManager
        sessions_dir = agent.memory.persist_directory / "sessions"
        session_manager = SessionManager(sessions_dir=sessions_dir)

        info = session_manager.get_session_info(session_id)
        if not info:
            # Try finding by name
            info = session_manager.find_session_by_name(session_id)

        if not info:
            console.print(f"[red]Session not found: {session_id}[/red]")
            console.print("[dim]Use 'session-list' to see available sessions[/dim]")
            return

        # Load the session
        agent.memory.load_session(session_id)

        # Restore permission mode
        if hasattr(info, 'permission_mode') and info.permission_mode:
            agent.set_permission_mode(info.permission_mode)

        console.print(f"\n[green]✓ Session loaded successfully![/green]")
        console.print(f"[dim]Session ID: {info.short_id}[/dim]")
        if info.name:
            console.print(f"[dim]Name: {info.name}[/dim]")
        console.print(f"[dim]Description: {info.task_description}[/dim]")
        console.print(f"[dim]Permission Mode: {info.permission_mode.upper() if hasattr(info, 'permission_mode') else 'NORMAL'}[/dim]")

        # Show what was loaded
        console.print(f"\n[cyan]Restored:[/cyan]")
        console.print(f"  • {info.message_count} messages")
        console.print(f"  • {len(agent.memory.episodic_memory.conversation_turns)} conversation turns")
        if agent.memory.working_memory.task_context:
            console.print(f"  • Task: {agent.memory.working_memory.task_context.description}")

        console.print(f"\n[dim]You can now continue working where you left off![/dim]")

    except Exception as e:
        console.print(f"[red]Error loading session: {e}[/red]")
        import traceback
        console.print(f"[dim]{traceback.format_exc()}[/dim]")


def delete_session_command(agent: CodingAgent, user_input: str) -> None:
    """Delete a saved session."""
    from rich.prompt import Confirm
    from src.core.session_manager import SessionManager

    parts = user_input.split(maxsplit=1)

    if len(parts) < 2:
        console.print("[yellow]Usage: session-delete <session-id>[/yellow]")
        console.print("[dim]Example: session-delete abc12345[/dim]")
        console.print("[dim]Use 'session-list' to see available sessions[/dim]")
        return

    session_id = parts[1].strip()

    try:
        sessions_dir = agent.memory.persist_directory / "sessions"
        session_manager = SessionManager(sessions_dir=sessions_dir)

        # Get info first
        info = session_manager.get_session_info(session_id)
        if not info:
            console.print(f"[red]Session not found: {session_id}[/red]")
            return

        # Show info and confirm
        console.print(f"\n[yellow]About to delete:[/yellow]")
        console.print(f"  ID: {info.short_id}")
        if info.name:
            console.print(f"  Name: {info.name}")
        console.print(f"  Description: {info.task_description}")
        console.print(f"  Messages: {info.message_count}")

        confirm = Confirm.ask("\n[red]Are you sure you want to delete this session?[/red]", default=False)

        if not confirm:
            console.print("[dim]Deletion cancelled.[/dim]")
            return

        # Delete
        success = session_manager.delete_session(session_id)

        if success:
            console.print(f"\n[green]✓ Session deleted successfully![/green]")
        else:
            console.print(f"[yellow]Session could not be deleted.[/yellow]")

    except Exception as e:
        console.print(f"[red]Error deleting session: {e}[/red]")


def session_info_command(agent: CodingAgent, user_input: str) -> None:
    """Show detailed information about a session."""
    from src.core.session_manager import SessionManager

    parts = user_input.split(maxsplit=1)

    if len(parts) < 2:
        console.print("[yellow]Usage: session-info <session-id|name>[/yellow]")
        console.print("[dim]Example: session-info abc12345[/dim]")
        return

    session_id = parts[1].strip()

    try:
        sessions_dir = agent.memory.persist_directory / "sessions"
        session_manager = SessionManager(sessions_dir=sessions_dir)

        # Get info
        info = session_manager.get_session_info(session_id)
        if not info:
            # Try finding by name
            info = session_manager.find_session_by_name(session_id)

        if not info:
            console.print(f"[red]Session not found: {session_id}[/red]")
            return

        # Display detailed info
        console.print()
        console.print(Panel.fit(
            f"[bold cyan]{info.name or 'Unnamed Session'}[/bold cyan]\n"
            f"[dim]ID: {info.session_id}[/dim]",
            border_style="cyan"
        ))

        console.print(f"\n[bold]Description:[/bold] {info.task_description}")
        console.print(f"[bold]Model:[/bold] {info.model_name}")

        # Timestamps
        from datetime import datetime
        created = info.created_datetime
        updated = info.updated_datetime
        console.print(f"\n[bold]Created:[/bold] {created.strftime('%Y-%m-%d %H:%M:%S')}")
        console.print(f"[bold]Updated:[/bold] {updated.strftime('%Y-%m-%d %H:%M:%S')}")

        # Statistics
        console.print(f"\n[bold]Statistics:[/bold]")
        console.print(f"  • Messages: {info.message_count}")
        console.print(f"  • Duration: {info.duration_minutes:.1f} minutes")

        # Tags
        if info.tags:
            console.print(f"\n[bold]Tags:[/bold] {', '.join(info.tags)}")

        console.print()
        console.print("[dim]Use 'session-load " + info.short_id + "' to resume this session[/dim]")

    except Exception as e:
        console.print(f"[red]Error getting session info: {e}[/red]")


# Checkpoint Commands

def create_checkpoint_command(controller: Optional[LongRunningController], user_input: str) -> None:
    """Create a checkpoint of current agent state."""
    if not controller:
        console.print("[red]Error: Controller not initialized[/red]")
        return

    # Parse optional description from command
    parts = user_input.split(maxsplit=1)
    description = parts[1] if len(parts) > 1 else None

    # If no description provided, ask for one
    if not description:
        description = Prompt.ask(
            "[cyan]Description[/cyan] (what did you accomplish?)",
            default="Manual checkpoint"
        )

    try:
        checkpoint_id = controller.create_checkpoint(description=description)

        if checkpoint_id:
            console.print(f"\n[green]Checkpoint created: {checkpoint_id}[/green]")
            console.print(f"[dim]Description: {description}[/dim]")
            console.print(f"[dim]Location: .checkpoints/[/dim]")
        else:
            console.print("[red]Failed to create checkpoint[/red]")

    except Exception as e:
        console.print(f"[red]Error creating checkpoint: {e}[/red]")


def list_checkpoints_command(controller: Optional[LongRunningController]) -> None:
    """List all saved checkpoints."""
    from rich.table import Table
    from datetime import datetime

    if not controller:
        console.print("[red]Error: Controller not initialized[/red]")
        return

    try:
        checkpoints = controller.list_checkpoints()

        if not checkpoints:
            console.print("[yellow]No checkpoints found.[/yellow]")
            console.print("[dim]Use 'checkpoint-save' to create your first checkpoint.[/dim]")
            return

        # Create table
        table = Table(title=f"Checkpoints ({len(checkpoints)} total)", show_header=True)
        table.add_column("ID", style="cyan", width=10)
        table.add_column("Description", style="white", width=40)
        table.add_column("Files", justify="right", style="blue", width=6)
        table.add_column("Tools", justify="right", style="magenta", width=6)
        table.add_column("Created", style="yellow", width=16)

        for checkpoint in checkpoints:
            # Format created time (relative)
            now = datetime.now()
            created = datetime.fromisoformat(checkpoint.timestamp)
            delta = now - created

            if delta.days > 0:
                created_str = f"{delta.days}d ago"
            elif delta.seconds > 3600:
                created_str = f"{delta.seconds // 3600}h ago"
            else:
                created_str = f"{delta.seconds // 60}m ago"

            table.add_row(
                checkpoint.checkpoint_id,
                checkpoint.task_description[:40] + ("..." if len(checkpoint.task_description) > 40 else ""),
                str(checkpoint.files_modified_count),
                str(checkpoint.tool_calls_count),
                created_str
            )

        console.print()
        console.print(table)
        console.print()
        console.print("[dim]Use 'checkpoint-restore <id>' to restore a checkpoint[/dim]")

    except Exception as e:
        console.print(f"[red]Error listing checkpoints: {e}[/red]")


def restore_checkpoint_command(controller: Optional[LongRunningController], user_input: str) -> None:
    """Restore a saved checkpoint."""
    from rich.prompt import Confirm

    if not controller:
        console.print("[red]Error: Controller not initialized[/red]")
        return

    parts = user_input.split(maxsplit=1)

    if len(parts) < 2:
        console.print("[yellow]Usage: checkpoint-restore <checkpoint-id>[/yellow]")
        console.print("[dim]Example: checkpoint-restore a1b2c3d4[/dim]")
        console.print("[dim]Use 'checkpoint-list' to see available checkpoints[/dim]")
        return

    checkpoint_id = parts[1].strip()

    # Confirm before restoring
    confirm = Confirm.ask(
        f"[yellow]Restore checkpoint {checkpoint_id}? This will restore agent state.[/yellow]",
        default=True
    )
    if not confirm:
        console.print("[dim]Restore cancelled.[/dim]")
        return

    try:
        success = controller.restore_checkpoint(checkpoint_id)

        if success:
            console.print(f"[green]Checkpoint {checkpoint_id} restored successfully![/green]")
        else:
            console.print(f"[red]Failed to restore checkpoint {checkpoint_id}[/red]")

    except Exception as e:
        console.print(f"[red]Error restoring checkpoint: {e}[/red]")


def clear_checkpoints_command(controller: Optional[LongRunningController]) -> None:
    """Delete all checkpoints."""
    from rich.prompt import Confirm

    if not controller:
        console.print("[red]Error: Controller not initialized[/red]")
        return

    # Get checkpoint count first
    checkpoints = controller.list_checkpoints()
    count = len(checkpoints)

    if count == 0:
        console.print("[yellow]No checkpoints to clear.[/yellow]")
        return

    # Confirm before clearing
    confirm = Confirm.ask(
        f"[yellow]Delete all {count} checkpoint(s)? This cannot be undone![/yellow]",
        default=False
    )
    if not confirm:
        console.print("[dim]Clear cancelled.[/dim]")
        return

    try:
        deleted = controller.clear_all_checkpoints()
        console.print(f"[green]Deleted {deleted} checkpoint(s)[/green]")

    except Exception as e:
        console.print(f"[red]Error clearing checkpoints: {e}[/red]")


def show_hooks_status(agent: CodingAgent) -> None:
    """Show current hooks status."""
    from rich.table import Table
    from pathlib import Path

    # Check if hook manager exists
    if not agent.hook_manager:
        console.print("[yellow]No hooks loaded.[/yellow]")
        console.print("[dim]Hooks are loaded from .clarity/hooks.py if it exists.[/dim]")
        console.print("[dim]Use 'hooks-examples' to see available examples.[/dim]")
        return

    # Check hooks file location
    hooks_path = Path(".clarity/hooks.py")
    hooks_file_status = "✓ Found" if hooks_path.exists() else "✗ Not found"

    console.print(f"\n[bold cyan]Hooks Status:[/bold cyan]")
    console.print(f"[dim]Hooks file (.clarity/hooks.py): {hooks_file_status}[/dim]")

    # Count registered hooks
    from src.hooks import HookEvent
    total_hooks = 0
    hooks_by_event = {}

    for event in HookEvent:
        event_hooks = agent.hook_manager.hooks.get(event, {})
        count = sum(len(funcs) for funcs in event_hooks.values())
        if count > 0:
            hooks_by_event[event.value] = event_hooks
            total_hooks += count

    if total_hooks == 0:
        console.print("\n[yellow]No hooks registered.[/yellow]")
        console.print("[dim]Add hooks to .clarity/hooks.py to extend agent behavior.[/dim]")
        return

    console.print(f"\n[green]✓ {total_hooks} hook(s) registered across {len(hooks_by_event)} event(s)[/green]\n")

    # Display hooks by event
    for event_name, tool_patterns in hooks_by_event.items():
        console.print(f"[bold cyan]{event_name}:[/bold cyan]")

        for pattern, funcs in tool_patterns.items():
            func_names = ", ".join(f.__name__ for f in funcs)
            pattern_display = pattern if pattern != '*' else '* (all tools)'
            console.print(f"  {pattern_display} → {func_names}")

        console.print()


def reload_hooks(agent: CodingAgent) -> None:
    """Reload hooks from .clarity/hooks.py."""
    from pathlib import Path
    from src.hooks import HookManager

    hooks_path = Path(".clarity/hooks.py")

    if not hooks_path.exists():
        console.print("[yellow]No hooks file found at .clarity/hooks.py[/yellow]")
        console.print("[dim]Use 'hooks-examples' to see available examples to get started.[/dim]")
        return

    try:
        # Create new hook manager
        new_manager = HookManager(hooks_file=hooks_path, session_id=agent.hook_manager.session_id if agent.hook_manager else None)

        # Replace agent's hook manager
        agent.hook_manager = new_manager

        # Update tool executor's hook manager
        agent.tool_executor.hook_manager = new_manager

        console.print(f"[green]✓ Hooks reloaded from {hooks_path}[/green]")

        # Show brief status
        from src.hooks import HookEvent
        total_hooks = sum(
            sum(len(funcs) for funcs in agent.hook_manager.hooks.get(event, {}).values())
            for event in HookEvent
        )

        if total_hooks > 0:
            console.print(f"[dim]Loaded {total_hooks} hook(s)[/dim]")
        else:
            console.print("[yellow]No hooks found in file (check HOOKS dictionary)[/yellow]")

    except Exception as e:
        console.print(f"[red]Error loading hooks: {e}[/red]")
        console.print("[dim]Check .clarity/hooks.py for syntax errors[/dim]")


def list_hook_examples() -> None:
    """List available hook examples."""
    from pathlib import Path
    from rich.table import Table

    examples_dir = Path(".clarity/examples")

    if not examples_dir.exists():
        console.print("[yellow]Examples directory not found at .clarity/examples[/yellow]")
        return

    # Get example files
    example_files = sorted(examples_dir.glob("*.py"))

    if not example_files:
        console.print("[yellow]No example files found in .clarity/examples[/yellow]")
        return

    console.print(f"\n[bold cyan]Available Hook Examples:[/bold cyan]\n")

    # Create table
    table = Table(show_header=True, show_lines=False)
    table.add_column("Example", style="cyan", width=20)
    table.add_column("Description", style="white", width=50)

    # Example descriptions (matching README.md)
    descriptions = {
        "validation.py": "Input validation - block dangerous operations and files",
        "backup.py": "Automatic backups - timestamped backups before changes",
        "audit.py": "Audit logging - comprehensive JSONL audit trail",
        "git_auto_commit.py": "Git auto-commit - automatic commits after changes",
        "rate_limiting.py": "Rate limiting - prevent runaway operations",
    }

    for example_file in example_files:
        if example_file.name == "__init__.py":
            continue

        desc = descriptions.get(example_file.name, "Hook example")
        table.add_row(example_file.name, desc)

    console.print(table)

    # Show usage instructions
    console.print(f"\n[dim]To use an example:[/dim]")
    console.print(f"[dim]  cp .clarity/examples/validation.py .clarity/hooks.py[/dim]")
    console.print(f"[dim]  # Edit .clarity/hooks.py to customize[/dim]")
    console.print(f"[dim]  # Run 'hooks-reload' to activate[/dim]")

    # Show README location
    readme_path = examples_dir / "README.md"
    if readme_path.exists():
        console.print(f"\n[dim]For detailed documentation, see: .clarity/examples/README.md[/dim]")


def show_help() -> None:
    """Show help information."""
    help_text = """
**Available Commands:**
- `exit/quit` - Exit the chat
- `help` - Show this help
- `stats` - Show agent statistics
- `clear` - Clear memory

**Session Commands:**
- `session-save` or `save [name]` - Save current session with metadata
- `session-list` or `sessions` - List all saved sessions
- `session-load <id>` - Load a saved session
- `session-delete <id>` - Delete a saved session
- `session-info <id>` - Show detailed session information

**Checkpoint Commands:**
- `checkpoint-save` or `checkpoint-create [desc]` - Save current work to checkpoint (resumable save point)
- `checkpoint-list` or `checkpoints` - List all saved checkpoints
- `checkpoint-restore <id>` - Restore agent state from checkpoint
- `checkpoint-clear` - Delete all checkpoints (WARNING: irreversible!)

**Memory Commands:**
- `memory` - Show current file memories
- `memory-init` - Create .opencodeagent/memory.md template
- `memory-add <text>` - Quick add memory (e.g., "memory-add Use 2-space indent")
- `memory-reload` - Reload file memories after editing

**Quick Reference:**
- `?` - Show quick reference guide with all shortcuts

**Permission Mode:**
- `Alt+M` - Quick toggle permission mode (plan -> normal -> auto)
- `/mode` - Toggle through modes
- `/mode p` - Set to Plan mode (always ask approval)
- `/mode n` - Set to Normal mode (balanced - default)
- `/mode a` - Set to Auto mode (fully autonomous)
  Current mode shown in prompt: [PLAN], [NORMAL], or [AUTO]

**Hooks Commands:**
- `hooks` or `hooks-status` - Show current hooks status
- `hooks-reload` - Reload hooks from .clarity/hooks.py
- `hooks-examples` - List available hook examples

**ClarAIty Commands:**
- `clarity-status` - Show ClarAIty status and configuration
- `clarity-scan` - Trigger full codebase scan
- `clarity-components` - List all components in database
- `clarity-stats` - Show database statistics
- `clarity-ui` - Launch ClarAIty web UI

**Available Tools:**
- read_file - Read a file
- write_file - Write to a file
- edit_file - Edit a file
- search_code - Search in code
- analyze_code - Analyze code structure

**File-Based Memory:**
The agent automatically loads memories from:
- `.opencodeagent/memory.md` (project-specific, version controlled)
- `~/.opencodeagent/memory.md` (user preferences)
- `/etc/opencodeagent/memory.md` (enterprise policies)

**Hooks System:**
Extend agent behavior with custom Python hooks:
- `.clarity/hooks.py` - Your custom hooks
- `.clarity/examples/` - Example hooks to get started
"""
    console.print(Markdown(help_text))


def show_stats(agent: CodingAgent) -> None:
    """Show agent statistics."""
    stats = agent.get_statistics()

    console.print("\n[bold cyan]Agent Statistics:[/bold cyan]")
    console.print(f"  Model: {stats['model']}")
    console.print(f"  Context Window: {stats['context_window']} tokens")
    console.print(f"  Indexed Chunks: {stats['indexed_chunks']}")

    memory_stats = stats['memory']
    console.print(f"\n[bold cyan]Memory:[/bold cyan]")
    console.print(f"  Working Memory: {memory_stats['working_memory']['tokens']} tokens")
    console.print(f"  Episodic Turns: {memory_stats['episodic_memory']['total_turns']}")
    console.print(f"  Session Duration: {memory_stats['session_duration_minutes']:.1f} min")


def task_mode(agent: CodingAgent, task: str, task_type: str = "implement") -> None:
    """Single task execution mode."""
    console.print(f"\n[bold cyan]Executing task:[/bold cyan] {task}\n")

    try:
        response = agent.execute_task(
            task_description=task,
            task_type=task_type,
            stream=True,
        )

        console.print(f"\n[green]Task completed![/green]")

    except Exception as e:
        console.print(f"[red]Error: {e}[/red]")


def index_mode(agent: CodingAgent, directory: str) -> None:
    """Index codebase mode."""
    console.print(f"\n[bold cyan]Indexing codebase:[/bold cyan] {directory}\n")

    try:
        stats = agent.index_codebase(directory=directory)

        console.print("\n[green]Indexing complete![/green]")
        console.print(f"  Files indexed: {stats['total_files']}")
        console.print(f"  Chunks created: {stats['total_chunks']}")
        console.print(f"  Languages: {', '.join(stats['languages'].keys())}")

    except Exception as e:
        console.print(f"[red]Error: {e}[/red]")


def show_clarity_status(agent: CodingAgent) -> None:
    """Show ClarAIty status and configuration."""
    if not hasattr(agent, 'clarity_hook') or agent.clarity_hook is None:
        console.print("[yellow]ClarAIty is not enabled or not available[/yellow]")
        return

    try:
        from src.clarity.config import get_config
        config = get_config()

        console.print("\n[bold cyan]ClarAIty Status:[/bold cyan]")
        console.print(f"  Enabled: [green]{config.enabled}[/green]")
        console.print(f"  Mode: {config.mode}")
        console.print(f"  Auto-sync: {config.auto_sync}")
        console.print(f"  Database: {config.db_path}")
        console.print(f"  LLM Model: {config.llm_model}")
        console.print(f"  API Port: {config.api_port}")
        console.print(f"  Approval UI Port: {config.approval_ui_port}")

    except Exception as e:
        console.print(f"[red]Error getting ClarAIty status: {e}[/red]")


def trigger_clarity_scan(agent: CodingAgent) -> None:
    """Trigger full codebase scan."""
    if not hasattr(agent, 'clarity_hook') or agent.clarity_hook is None:
        console.print("[yellow]ClarAIty is not enabled[/yellow]")
        return

    try:
        from src.clarity.sync import SyncOrchestrator
        from src.clarity.config import get_config
        from pathlib import Path
        import asyncio

        config = get_config()
        clarity_db = agent.clarity_hook.clarity_db

        if not clarity_db:
            console.print("[yellow]ClarAIty database not initialized[/yellow]")
            return

        console.print("\n[cyan]Starting full codebase scan...[/cyan]")

        orchestrator = SyncOrchestrator(
            clarity_db=clarity_db,
            working_directory=str(Path.cwd()),
            auto_sync=False
        )

        # Run full rescan
        result = asyncio.run(orchestrator.full_rescan())

        console.print(f"\n[green]✓ Scan complete![/green]")
        console.print(f"  Files analyzed: {result.files_analyzed}")
        console.print(f"  Components added: {result.components_added}")
        console.print(f"  Components updated: {result.components_updated}")
        console.print(f"  Duration: {result.duration_seconds:.2f}s")

    except Exception as e:
        console.print(f"[red]Error triggering scan: {e}[/red]")
        import traceback
        traceback.print_exc()


def list_clarity_components(agent: CodingAgent) -> None:
    """List all components in ClarAIty database."""
    if not hasattr(agent, 'clarity_hook') or agent.clarity_hook is None:
        console.print("[yellow]ClarAIty is not enabled[/yellow]")
        return

    try:
        clarity_db = agent.clarity_hook.clarity_db
        if not clarity_db:
            console.print("[yellow]ClarAIty database not initialized[/yellow]")
            return

        components = clarity_db.get_all_components()

        if not components:
            console.print("[yellow]No components found in database[/yellow]")
            console.print("[dim]Run 'clarity-scan' to populate the database[/dim]")
            return

        console.print(f"\n[bold cyan]Components ({len(components)}):[/bold cyan]")

        # Group by layer
        by_layer = {}
        for comp in components:
            layer = comp.get('layer', 'unknown')
            if layer not in by_layer:
                by_layer[layer] = []
            by_layer[layer].append(comp)

        for layer, comps in sorted(by_layer.items()):
            console.print(f"\n[bold]{layer}:[/bold]")
            for comp in comps[:10]:  # Show first 10 per layer
                console.print(f"  • {comp['name']} ({comp['type']})")
            if len(comps) > 10:
                console.print(f"  [dim]... and {len(comps) - 10} more[/dim]")

    except Exception as e:
        console.print(f"[red]Error listing components: {e}[/red]")


def show_clarity_stats(agent: CodingAgent) -> None:
    """Show ClarAIty database statistics."""
    if not hasattr(agent, 'clarity_hook') or agent.clarity_hook is None:
        console.print("[yellow]ClarAIty is not enabled[/yellow]")
        return

    try:
        clarity_db = agent.clarity_hook.clarity_db
        if not clarity_db:
            console.print("[yellow]ClarAIty database not initialized[/yellow]")
            return

        stats = clarity_db.get_statistics()

        console.print("\n[bold cyan]ClarAIty Database Statistics:[/bold cyan]")
        console.print(f"  Total Components: {stats.get('total_components', 0)}")
        console.print(f"  Total Artifacts: {stats.get('total_artifacts', 0)}")
        console.print(f"  Total Relationships: {stats.get('total_relationships', 0)}")
        console.print(f"  Total Flows: {stats.get('total_flows', 0)}")
        console.print(f"  Total Design Decisions: {stats.get('total_design_decisions', 0)}")

    except Exception as e:
        console.print(f"[red]Error getting stats: {e}[/red]")


def launch_clarity_ui(agent: CodingAgent) -> None:
    """Launch ClarAIty web UI."""
    if not hasattr(agent, 'clarity_hook') or agent.clarity_hook is None:
        console.print("[yellow]ClarAIty is not enabled[/yellow]")
        return

    try:
        from src.clarity.api.server import run_server
        from src.clarity.config import get_config
        import threading

        config = get_config()

        console.print(f"\n[cyan]Starting ClarAIty API server on port {config.api_port}...[/cyan]")
        console.print(f"[dim]API docs: http://localhost:{config.api_port}/docs[/dim]")
        console.print(f"[dim]Press Ctrl+C to stop[/dim]\n")

        # Run server (blocking)
        run_server(
            host="0.0.0.0",
            port=config.api_port,
            config=config
        )

    except KeyboardInterrupt:
        console.print("\n[yellow]Server stopped[/yellow]")
    except Exception as e:
        console.print(f"[red]Error launching UI: {e}[/red]")
        import traceback
        traceback.print_exc()


def main() -> None:
    """Main CLI entry point."""
    # Note: Logging auto-configures on first get_logger() call during imports.
    # All logs go to JSONL file only - no console output.
    # User-facing messages use Rich console.print().

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

    # Embedding configuration
    parser.add_argument(
        "--embedding-model",
        default=os.environ.get("EMBEDDING_MODEL"),
        help="Embedding model name (from .env: EMBEDDING_MODEL)"
    )

    parser.add_argument(
        "--embedding-api-key",
        default=None,
        help="API key for embedding service (optional, uses env var if not provided)"
    )

    parser.add_argument(
        "--embedding-api-key-env",
        default=os.environ.get("EMBEDDING_API_KEY_ENV", "EMBEDDING_API_KEY"),
        help="Environment variable name for embedding API key (default: EMBEDDING_API_KEY)"
    )

    parser.add_argument(
        "--embedding-base-url",
        default=os.environ.get("EMBEDDING_BASE_URL"),
        help="Embedding API base URL (from .env: EMBEDDING_BASE_URL)"
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

    subparsers = parser.add_subparsers(dest="command", help="Available commands")

    # Chat command
    subparsers.add_parser("chat", help="Interactive chat mode")

    # Task command
    task_parser = subparsers.add_parser("task", help="Execute a single task")
    task_parser.add_argument("description", help="Task description")
    task_parser.add_argument(
        "--type",
        default="implement",
        choices=["implement", "debug", "refactor", "explain", "test", "review"],
        help="Task type"
    )

    # Index command
    index_parser = subparsers.add_parser("index", help="Index codebase for RAG")
    index_parser.add_argument(
        "directory",
        nargs="?",
        default=".",
        help="Directory to index (default: current)"
    )

    args = parser.parse_args()

    # ---------------------------------------------------------------
    # Unified config: YAML file + env vars + CLI args (layered)
    # ---------------------------------------------------------------
    from src.llm.config_loader import load_llm_config, resolve_llm_config

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

    # In TUI mode (default "chat"), launch without agent if config is missing
    # The TUI will auto-present the config wizard
    is_tui_mode = (not hasattr(args, 'command') or args.command is None or args.command == "chat")

    if not llm_configured and not is_tui_mode:
        # Non-TUI modes (task, index) require a fully configured LLM
        if not llm_config.model:
            console.print("[red]Error: No LLM model configured.[/red]")
        if not llm_config.backend_type:
            console.print("[red]Error: No LLM backend configured.[/red]")
        if not llm_config.base_url:
            console.print("[red]Error: No LLM API URL configured.[/red]")
        console.print("[yellow]Configure via: Ctrl+P > 'Configure LLM' in TUI, or set LLM_MODEL env var, or add llm.model to .clarity/config.yaml[/yellow]")
        sys.exit(1)

    if not llm_configured and is_tui_mode:
        # Launch TUI without agent -- it will auto-show the config wizard
        console.print("[yellow]No LLM configured. Launching setup wizard...[/yellow]")
        cli_log_level = args.log_level
        from src.observability.logging_config import configure_logging
        configure_logging(mode="cli", log_level=cli_log_level)
        chat_mode(agent=None, controller=None, log_level=cli_log_level, llm_config=llm_config)
        return

    # Initialize agent
    console.print(f"\n[cyan]Initializing AI Coding Agent...[/cyan]")
    console.print(f"Model: {llm_config.model}")
    console.print(f"Backend: {llm_config.backend_type}")
    console.print(f"URL: {llm_config.base_url}")

    # Resolve API key: CLI flag > keyring > env var
    # (llm_config.api_key is already populated from keyring/env by load_llm_config)
    resolved_api_key = args.api_key or llm_config.api_key

    try:
        agent = CodingAgent(
            model_name=llm_config.model,
            backend=llm_config.backend_type,
            base_url=llm_config.base_url,
            context_window=llm_config.context_window,
            temperature=llm_config.temperature,
            max_tokens=llm_config.max_tokens,
            top_p=llm_config.top_p,
            api_key=resolved_api_key,
            api_key_env=llm_config.api_key_env,
            embedding_model=args.embedding_model,
            embedding_api_key=args.embedding_api_key,
            embedding_api_key_env=args.embedding_api_key_env,
            embedding_base_url=args.embedding_base_url,
            permission_mode=args.permission,
        )

        # Apply subagent LLM overrides from config.yaml
        if llm_config.subagents and hasattr(agent, 'subagent_manager'):
            agent.subagent_manager.config_loader.apply_llm_overrides(llm_config)

        # Check if backend is available
        if not agent.llm.is_available():
            console.print(f"[red]Error: {llm_config.backend_type} backend not available at {llm_config.base_url}[/red]")
            console.print(f"[yellow]Make sure {llm_config.backend_type} is running and accessible[/yellow]")
            sys.exit(1)

        console.print(f"[green]Agent initialized successfully![/green]\n")

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

        # Note: Auto-indexing removed - use 'memory-init' command in chat or 'index' command explicitly
        # Indexing should be on-demand when LLM decides it's needed, or user requests it

        # Configure logging early so all modes get config.yaml + --log-level
        # chat_mode/simple_chat_mode also call configure_logging, but the
        # _configured guard makes double-calling safe.
        cli_log_level = args.log_level
        from src.observability.logging_config import configure_logging
        configure_logging(mode="cli", log_level=cli_log_level)

        # Execute command
        if args.command == "chat":
            chat_mode(agent, controller, log_level=cli_log_level, llm_config=llm_config)
        elif args.command == "task":
            task_mode(agent, args.description, args.type)
        elif args.command == "index":
            index_mode(agent, args.directory)
        else:
            # Default to chat mode
            chat_mode(agent, controller, log_level=cli_log_level, llm_config=llm_config)

    except Exception as e:
        console.print(f"[red]Failed to initialize agent: {e}[/red]")
        sys.exit(1)


if __name__ == "__main__":
    main()
