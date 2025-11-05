"""Command-line interface for the AI coding agent."""

import sys
from pathlib import Path
from typing import Optional
import argparse

from rich.console import Console
from rich.markdown import Markdown
from rich.panel import Panel
from rich.prompt import Prompt

from src.core import CodingAgent


console = Console()


def chat_mode(agent: CodingAgent) -> None:
    """Interactive chat mode."""
    console.print(Panel.fit(
        "[bold cyan]AI Coding Agent - Interactive Mode[/bold cyan]\n"
        f"Model: {agent.model_name}\n"
        f"Context: {agent.context_window} tokens\n"
        "Type 'exit' or 'quit' to leave, 'help' for commands",
        border_style="cyan"
    ))

    while True:
        try:
            # Get user input
            user_input = Prompt.ask("\n[bold green]You[/bold green]")

            if not user_input.strip():
                continue

            # Handle commands
            if user_input.lower() in ["exit", "quit", "q"]:
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

            # Permission mode commands
            if user_input.lower() in ["permission", "permission-mode", "p"]:
                show_permission_mode(agent)
                continue

            if user_input.lower().startswith("permission-set"):
                parts = user_input.split(maxsplit=1)
                if len(parts) < 2:
                    console.print("[yellow]Usage: permission-set <mode>[/yellow]")
                    console.print("[dim]Valid modes: plan, normal, auto[/dim]")
                    continue
                set_permission_mode(agent, parts[1])
                continue

            # Quick permission mode toggle (like Shift+Tab in Claude Code)
            if user_input.lower() in ["permission-toggle", "pt", "/mode"]:
                toggle_permission_mode(agent)
                continue

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

            # Process with agent
            console.print("\n[bold blue]Agent[/bold blue]")
            response = agent.chat(user_input, stream=True)

        except KeyboardInterrupt:
            console.print("\n[yellow]Interrupted. Type 'exit' to quit.[/yellow]")
            continue
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

        # Show quick status with emoji
        mode_emoji = {
            "plan": "📋",
            "normal": "⚖️",
            "auto": "🤖"
        }

        emoji = mode_emoji.get(next_mode, "")
        console.print(f"\n{emoji} [bold green]Permission mode: {current_mode} → {next_mode}[/bold green]")

        # Show brief description
        descriptions = {
            "plan": "Always ask for approval (review mode)",
            "normal": "Ask only for high-risk operations (balanced)",
            "auto": "Never ask for approval (fully autonomous)"
        }
        console.print(f"[dim]{descriptions.get(next_mode, '')}[/dim]\n")

    except Exception as e:
        console.print(f"[red]Error toggling permission mode: {e}[/red]")


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
            tags=tags
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
        table.add_column("Description", style="white", width=30)
        table.add_column("Messages", justify="right", style="blue", width=8)
        table.add_column("Duration", justify="right", style="magenta", width=10)
        table.add_column("Updated", style="yellow", width=16)
        table.add_column("Tags", style="dim", width=20)

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

            table.add_row(
                session.short_id,
                session.name or "[dim]unnamed[/dim]",
                session.task_description[:30] + ("..." if len(session.task_description) > 30 else ""),
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
            f"[yellow]⚠ Loading will clear current conversation. Continue?[/yellow]",
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

        console.print(f"\n[green]✓ Session loaded successfully![/green]")
        console.print(f"[dim]Session ID: {info.short_id}[/dim]")
        if info.name:
            console.print(f"[dim]Name: {info.name}[/dim]")
        console.print(f"[dim]Description: {info.task_description}[/dim]")

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


def show_hooks_status(agent: CodingAgent) -> None:
    """Show current hooks status."""
    from rich.table import Table
    from pathlib import Path

    # Check if hook manager exists
    if not agent.hook_manager:
        console.print("[yellow]No hooks loaded.[/yellow]")
        console.print("[dim]Hooks are loaded from .claude/hooks.py if it exists.[/dim]")
        console.print("[dim]Use 'hooks-examples' to see available examples.[/dim]")
        return

    # Check hooks file location
    hooks_path = Path(".claude/hooks.py")
    hooks_file_status = "✓ Found" if hooks_path.exists() else "✗ Not found"

    console.print(f"\n[bold cyan]Hooks Status:[/bold cyan]")
    console.print(f"[dim]Hooks file (.claude/hooks.py): {hooks_file_status}[/dim]")

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
        console.print("[dim]Add hooks to .claude/hooks.py to extend agent behavior.[/dim]")
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
    """Reload hooks from .claude/hooks.py."""
    from pathlib import Path
    from src.hooks import HookManager

    hooks_path = Path(".claude/hooks.py")

    if not hooks_path.exists():
        console.print("[yellow]No hooks file found at .claude/hooks.py[/yellow]")
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
        console.print("[dim]Check .claude/hooks.py for syntax errors[/dim]")


def list_hook_examples() -> None:
    """List available hook examples."""
    from pathlib import Path
    from rich.table import Table

    examples_dir = Path(".claude/examples")

    if not examples_dir.exists():
        console.print("[yellow]Examples directory not found at .claude/examples[/yellow]")
        return

    # Get example files
    example_files = sorted(examples_dir.glob("*.py"))

    if not example_files:
        console.print("[yellow]No example files found in .claude/examples[/yellow]")
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
    console.print(f"[dim]  cp .claude/examples/validation.py .claude/hooks.py[/dim]")
    console.print(f"[dim]  # Edit .claude/hooks.py to customize[/dim]")
    console.print(f"[dim]  # Run 'hooks-reload' to activate[/dim]")

    # Show README location
    readme_path = examples_dir / "README.md"
    if readme_path.exists():
        console.print(f"\n[dim]For detailed documentation, see: .claude/examples/README.md[/dim]")


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

**Memory Commands:**
- `memory` - Show current file memories
- `memory-init` - Create .opencodeagent/memory.md template
- `memory-add <text>` - Quick add memory (e.g., "memory-add Use 2-space indent")
- `memory-reload` - Reload file memories after editing

**Permission Commands:**
- `permission` or `p` - Show current permission mode
- `permission-toggle` or `pt` or `/mode` - 🔄 Quick toggle (plan → normal → auto → plan)
- `permission-set <mode>` - Set permission mode (plan/normal/auto)
  - `plan`: Always ask for approval before executing
  - `normal`: Ask only for high-risk operations (default)
  - `auto`: Never ask for approval (fully autonomous)

**Hooks Commands:**
- `hooks` or `hooks-status` - Show current hooks status
- `hooks-reload` - Reload hooks from .claude/hooks.py
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
- `.claude/hooks.py` - Your custom hooks
- `.claude/examples/` - Example hooks to get started
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
    parser = argparse.ArgumentParser(
        description="AI Coding Agent - Optimized for small open-source LLMs"
    )

    parser.add_argument(
        "--model",
        default="qwen3-coder:30b",
        help="Model name (default: qwen3-coder:30b)"
    )

    parser.add_argument(
        "--backend",
        default="ollama",
        choices=["ollama", "openai"],
        help="LLM backend (default: ollama, openai for API services)"
    )

    parser.add_argument(
        "--url",
        default="http://localhost:11434",
        help="Backend API URL (default: http://localhost:11434)"
    )

    parser.add_argument(
        "--context",
        type=int,
        default=131072,
        help="Context window size (default: 131072 - 128K)"
    )

    parser.add_argument(
        "--api-key",
        default=None,
        help="API key for OpenAI-compatible backends (can also use env var)"
    )

    parser.add_argument(
        "--api-key-env",
        default="OPENAI_API_KEY",
        help="Environment variable name for API key (default: OPENAI_API_KEY, use DASHSCOPE_API_KEY for Alibaba)"
    )

    parser.add_argument(
        "--permission",
        default="normal",
        choices=["plan", "normal", "auto"],
        help="Permission mode: plan (always ask), normal (ask for risky ops), auto (never ask) (default: normal)"
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

    # Initialize agent
    console.print(f"\n[cyan]Initializing AI Coding Agent...[/cyan]")
    console.print(f"Model: {args.model}")
    console.print(f"Backend: {args.backend}")

    try:
        agent = CodingAgent(
            model_name=args.model,
            backend=args.backend,
            base_url=args.url,
            context_window=args.context,
            api_key=args.api_key,
            api_key_env=args.api_key_env,
            permission_mode=args.permission,
        )

        # Check if backend is available
        if not agent.llm.is_available():
            console.print(f"[red]Error: {args.backend} backend not available at {args.url}[/red]")
            console.print(f"[yellow]Make sure {args.backend} is running and accessible[/yellow]")
            sys.exit(1)

        console.print(f"[green]Agent initialized successfully![/green]\n")

        # Auto-index codebase for chat mode if not explicitly indexing
        if args.command in ["chat", None]:
            if len(agent.indexed_chunks) == 0:
                console.print("[yellow]Auto-indexing codebase for RAG...[/yellow]")
                try:
                    result = agent.index_codebase("./src")
                    console.print(f"[green]✓ Indexed {result['total_files']} files, {result['total_chunks']} chunks[/green]\n")
                except Exception as e:
                    console.print(f"[yellow]⚠ Could not index codebase: {e}[/yellow]\n")

        # Execute command
        if args.command == "chat":
            chat_mode(agent)
        elif args.command == "task":
            task_mode(agent, args.description, args.type)
        elif args.command == "index":
            index_mode(agent, args.directory)
        else:
            # Default to chat mode
            chat_mode(agent)

    except Exception as e:
        console.print(f"[red]Failed to initialize agent: {e}[/red]")
        sys.exit(1)


if __name__ == "__main__":
    main()
