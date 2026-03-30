"""Start the ClarAIty VS Code server.

Usage:
    python -m src.server --stdio --data-port 12345

Windows note:
    Uses the default ProactorEventLoop on Windows. This is required for
    asyncio.create_subprocess_exec() (used by subagent delegation).
"""

import argparse
import asyncio
import os
import sys


def main():

    parser = argparse.ArgumentParser(description="ClarAIty VS Code Server")
    parser.add_argument("--workdir", default=None, help="Working directory (default: cwd)")
    parser.add_argument(
        "--config", default=None, help="Config file path (default: .claraity/config.yaml)"
    )
    parser.add_argument(
        "--stdio", action="store_true", help="Use stdio transport (stdin/stdout JSON lines)"
    )
    parser.add_argument(
        "--data-port",
        type=int,
        default=0,
        help="TCP port for data channel (used with --stdio to bypass pipe issues on Windows)",
    )
    parser.add_argument(
        "--subagent",
        action="store_true",
        help="Run as subagent subprocess (reads task JSON from stdin, emits events on stdout)",
    )
    args = parser.parse_args()

    # Subagent mode: delegate to src.subagents.runner.main() immediately.
    # This is used when the bundled binary spawns subagent subprocesses —
    # sys.executable is the .exe so we can't use `python -m src.subagents.runner`.
    if args.subagent:
        from src.subagents.runner import main as runner_main

        runner_main()
        return

    working_directory = args.workdir or os.getcwd()

    # Resolve config path: explicit flag > project config > system config
    from src.llm.config_loader import SYSTEM_CONFIG_PATH

    if args.config:
        config_path = args.config
    else:
        project_config = os.path.join(working_directory, ".claraity", "config.yaml")
        config_path = project_config if os.path.isfile(project_config) else SYSTEM_CONFIG_PATH

    # stdio mode: stdin for commands, TCP for events (for VS Code extension)
    if args.stdio:
        from src.server.stdio_server import run_stdio_server

        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)
        try:
            loop.run_until_complete(
                run_stdio_server(
                    working_directory=working_directory,
                    config_path=config_path,
                    permission_mode="auto",
                    data_port=args.data_port,
                )
            )
        except KeyboardInterrupt:
            pass
        finally:
            loop.close()
        return

    # No transport specified
    print("Error: --stdio is required. Usage: python -m src.server --stdio --data-port PORT")
    sys.exit(1)


if __name__ == "__main__":
    try:
        main()
    except Exception as e:
        import traceback

        sys.stderr.write(f"\n[FATAL] {e}\n")
        traceback.print_exc(file=sys.stderr)
        sys.stderr.flush()
        sys.exit(1)
