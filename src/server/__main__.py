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

import sys
import asyncio
import argparse
import os
import signal


def main():

    parser = argparse.ArgumentParser(description="ClarAIty VS Code Server")
    parser.add_argument("--host", default="127.0.0.1", help="Bind address (default: 127.0.0.1)")
    parser.add_argument("--port", type=int, default=9120, help="Port (default: 9120)")
    parser.add_argument("--workdir", default=None, help="Working directory (default: cwd)")
    parser.add_argument("--config", default=None, help="Config file path (default: .clarity/config.yaml)")
    args = parser.parse_args()

    working_directory = args.workdir or os.getcwd()

    # Load LLM config from config.yaml (same as CLI)
    from src.llm.config_loader import load_llm_config, SYSTEM_CONFIG_PATH

    config_path = args.config or SYSTEM_CONFIG_PATH
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
    main()
