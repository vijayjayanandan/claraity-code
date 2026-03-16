"""Start the ClarAIty VS Code server.

Usage:
    python -m src.server                    # Default: localhost:9120
    python -m src.server --port 9121        # Custom port
    python -m src.server --host 0.0.0.0     # Bind all interfaces (not recommended)

Windows note:
    Uses the default ProactorEventLoop on Windows. This is required for
    asyncio.create_subprocess_exec() (used by subagent delegation).
    aiohttp 3.9+ works correctly with ProactorEventLoop.
"""

import argparse
import asyncio
import os
import signal
import sys


def main():

    parser = argparse.ArgumentParser(description="ClarAIty VS Code Server")
    parser.add_argument("--host", default="127.0.0.1", help="Bind address (default: 127.0.0.1)")
    parser.add_argument("--port", type=int, default=9120, help="Port (default: 9120)")
    parser.add_argument("--workdir", default=None, help="Working directory (default: cwd)")
    parser.add_argument(
        "--config", default=None, help="Config file path (default: .clarity/config.yaml)"
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
        project_config = os.path.join(working_directory, ".clarity", "config.yaml")
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

    # WebSocket mode: HTTP+WS server (default)
    from src.llm.config_loader import load_llm_config

    print(f"Loading config from: {config_path}")
    llm_config = load_llm_config(config_path)

    print(f"Model: {llm_config.model}")
    print(f"Backend: {llm_config.backend_type}")
    print(f"URL: {llm_config.base_url}")

    # Import here to avoid triggering logging config at module level
    from src.server.app import AgentServer

    server = AgentServer(
        host=args.host,
        port=args.port,
        working_directory=working_directory,
        config_path=config_path,
        permission_mode="auto",  # VS Code uses auto mode by default
        api_key=llm_config.api_key,
    )

    loop = asyncio.new_event_loop()
    asyncio.set_event_loop(loop)

    async def run():
        try:
            await server.start()
        except Exception as e:
            print(f"\n[ERROR] Server failed to start: {e}")
            import traceback

            traceback.print_exc()
            return

        # Keep running until interrupted.
        # On Unix we use signal handlers; on Windows we rely on
        # KeyboardInterrupt propagating through the sleep loop.
        if sys.platform != "win32":
            stop_event = asyncio.Event()
            for sig in (signal.SIGINT, signal.SIGTERM):
                loop.add_signal_handler(sig, stop_event.set)
            await stop_event.wait()
        else:
            # Windows: asyncio signal handlers not supported.
            # Use a simple sleep loop that KeyboardInterrupt can break.
            while True:
                await asyncio.sleep(1)

    try:
        loop.run_until_complete(run())
    except KeyboardInterrupt:
        print("\nShutting down...")
        loop.run_until_complete(server.stop())
    finally:
        loop.close()


if __name__ == "__main__":
    try:
        main()
    except Exception as e:
        import traceback

        sys.stderr.write(f"\n[FATAL] {e}\n")
        traceback.print_exc(file=sys.stderr)
        sys.stderr.flush()
        sys.exit(1)
