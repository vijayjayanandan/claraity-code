#!/usr/bin/env python3
"""
LSP Performance Benchmark Script

Measures and attributes latency across:
- Manager init
- Server start / warmup
- Query execution
- Cache/reuse behavior across calls

Usage:
    python scripts/bench_lsp.py              # Normal mode (reuses manager)
    python scripts/bench_lsp.py --fresh      # Fresh process per call
    python scripts/bench_lsp.py --verbose    # Enable debug logging
"""

import argparse
import asyncio
import logging
import sys
import time
from pathlib import Path

# Add project root to path
sys.path.insert(0, str(Path(__file__).parent.parent))

from src.code_intelligence.lsp_client_manager import LSPClientManager


def setup_logging(verbose: bool = False):
    """Configure logging for benchmark."""
    level = logging.DEBUG if verbose else logging.INFO

    # Format: time - logger - level - message
    formatter = logging.Formatter(
        '%(asctime)s.%(msecs)03d - %(name)s - %(levelname)s - %(message)s',
        datefmt='%H:%M:%S'
    )

    handler = logging.StreamHandler(sys.stdout)
    handler.setFormatter(formatter)
    handler.setLevel(level)

    # Configure root logger
    root_logger = logging.getLogger()
    root_logger.setLevel(level)
    root_logger.handlers = [handler]

    # Make sure our loggers use the handler
    for logger_name in ['code_intelligence.lsp_manager', 'code_intelligence.cache']:
        logger = logging.getLogger(logger_name)
        logger.setLevel(level)
        logger.handlers = []
        logger.addHandler(handler)


async def run_single_query(manager: LSPClientManager, file_path: str, run_num: int) -> dict:
    """Run a single document symbols query and measure timing."""
    print(f"\n{'='*60}")
    print(f"RUN #{run_num}")
    print(f"{'='*60}")

    start = time.perf_counter()

    try:
        result = await manager.request_document_symbols(file_path)
        elapsed_ms = (time.perf_counter() - start) * 1000

        print(f"\n[RESULT] Run #{run_num}: {elapsed_ms:.1f}ms")
        print(f"  Symbols found: {len(result)}")

        return {
            "run": run_num,
            "success": True,
            "elapsed_ms": elapsed_ms,
            "symbols": len(result)
        }

    except Exception as e:
        elapsed_ms = (time.perf_counter() - start) * 1000
        print(f"\n[ERROR] Run #{run_num}: {elapsed_ms:.1f}ms - {e}")

        return {
            "run": run_num,
            "success": False,
            "elapsed_ms": elapsed_ms,
            "error": str(e)
        }


async def benchmark_reuse_mode(file_path: str, num_runs: int = 3) -> list:
    """
    Benchmark with server reuse (single manager for all runs).

    This tests whether the server is actually being reused between calls.
    """
    print("\n" + "="*70)
    print("BENCHMARK MODE: Server Reuse (Single Manager)")
    print("="*70)
    print(f"File: {file_path}")
    print(f"Runs: {num_runs}")

    # Create single manager
    init_start = time.perf_counter()
    manager = LSPClientManager()
    init_ms = (time.perf_counter() - init_start) * 1000
    print(f"\nManager init: {init_ms:.1f}ms")
    print(f"Manager id: {id(manager)}")

    # Get event loop identity
    try:
        loop = asyncio.get_running_loop()
        print(f"Event loop id: {id(loop)}")
    except RuntimeError:
        print("Event loop id: N/A")

    results = []
    for i in range(1, num_runs + 1):
        result = await run_single_query(manager, file_path, i)
        result["manager_id"] = id(manager)
        results.append(result)

    return results


async def benchmark_fresh_mode(file_path: str, num_runs: int = 3) -> list:
    """
    Benchmark with fresh manager per call.

    This simulates the current behavior where lsp_tools.py resets
    self.lsp_manager = None before each call.
    """
    print("\n" + "="*70)
    print("BENCHMARK MODE: Fresh Manager Per Call")
    print("="*70)
    print(f"File: {file_path}")
    print(f"Runs: {num_runs}")

    results = []
    for i in range(1, num_runs + 1):
        # Create fresh manager each time
        init_start = time.perf_counter()
        manager = LSPClientManager()
        init_ms = (time.perf_counter() - init_start) * 1000
        print(f"\n[Run #{i}] Fresh manager created: {init_ms:.1f}ms, id={id(manager)}")

        result = await run_single_query(manager, file_path, i)
        result["manager_id"] = id(manager)
        result["init_ms"] = init_ms
        results.append(result)

        # Note: Server connection will be orphaned when manager goes out of scope
        # This is the bug we're investigating

    return results


def print_summary(results: list, mode: str):
    """Print benchmark summary."""
    print("\n" + "="*70)
    print(f"SUMMARY ({mode})")
    print("="*70)

    successful = [r for r in results if r["success"]]
    failed = [r for r in results if not r["success"]]

    if successful:
        times = [r["elapsed_ms"] for r in successful]
        print(f"\nSuccessful runs: {len(successful)}/{len(results)}")
        print(f"  Run 1 (cold): {times[0]:.1f}ms")
        if len(times) > 1:
            print(f"  Run 2 (warm): {times[1]:.1f}ms")
        if len(times) > 2:
            print(f"  Run 3 (warm): {times[2]:.1f}ms")
        print(f"\n  Average: {sum(times)/len(times):.1f}ms")
        print(f"  Min: {min(times):.1f}ms")
        print(f"  Max: {max(times):.1f}ms")

        # Check for reuse pattern
        if len(times) >= 2:
            speedup = times[0] / times[1] if times[1] > 0 else 0
            if speedup > 5:
                print(f"\n  [GOOD] Significant speedup on run 2: {speedup:.1f}x")
                print("  Server appears to be reused correctly.")
            elif speedup > 1.5:
                print(f"\n  [OK] Moderate speedup on run 2: {speedup:.1f}x")
                print("  Some caching may be working.")
            else:
                print(f"\n  [BAD] No speedup on run 2: {speedup:.1f}x")
                print("  Server is likely NOT being reused!")

    if failed:
        print(f"\nFailed runs: {len(failed)}")
        for r in failed:
            print(f"  Run {r['run']}: {r.get('error', 'Unknown error')}")

    # Manager identity analysis
    manager_ids = set(r["manager_id"] for r in results)
    if len(manager_ids) == 1:
        print(f"\n  Manager ID: {list(manager_ids)[0]} (same for all runs)")
    else:
        print(f"\n  Manager IDs: {manager_ids} (DIFFERENT - fresh per call)")


def main():
    parser = argparse.ArgumentParser(description="LSP Performance Benchmark")
    parser.add_argument(
        "--fresh",
        action="store_true",
        help="Create fresh manager for each call (simulates current bug)"
    )
    parser.add_argument(
        "--verbose", "-v",
        action="store_true",
        help="Enable debug logging"
    )
    parser.add_argument(
        "--file",
        type=str,
        default="src/tools/lsp_tools.py",
        help="File to analyze (default: src/tools/lsp_tools.py)"
    )
    parser.add_argument(
        "--runs",
        type=int,
        default=3,
        help="Number of runs (default: 3)"
    )

    args = parser.parse_args()

    setup_logging(args.verbose)

    # Resolve file path
    file_path = str(Path(args.file).resolve())
    if not Path(file_path).exists():
        print(f"Error: File not found: {file_path}")
        sys.exit(1)

    print("\n" + "="*70)
    print("LSP PERFORMANCE BENCHMARK")
    print("="*70)
    print(f"\nTarget file: {file_path}")
    print(f"Mode: {'Fresh manager per call' if args.fresh else 'Reuse manager'}")
    print(f"Runs: {args.runs}")
    print(f"Verbose: {args.verbose}")

    # Run benchmark
    if args.fresh:
        results = asyncio.run(benchmark_fresh_mode(file_path, args.runs))
        print_summary(results, "Fresh Manager Per Call")
    else:
        results = asyncio.run(benchmark_reuse_mode(file_path, args.runs))
        print_summary(results, "Server Reuse")

    # Diagnosis
    print("\n" + "="*70)
    print("DIAGNOSIS")
    print("="*70)

    if args.fresh:
        print("""
This mode simulates the CURRENT behavior where lsp_tools.py
sets self.lsp_manager = None before each call.

If all runs are slow (~15-25s each):
  -> The server is being restarted every call
  -> Fix: Preserve the manager across calls within same event loop

If run 1 is slow but runs 2-3 are fast:
  -> Something else is caching (unlikely in fresh mode)
""")
    else:
        times = [r["elapsed_ms"] for r in results if r["success"]]
        if times:
            if times[0] > 10000 and (len(times) < 2 or times[1] > 10000):
                print("""
[ISSUE] All runs are slow (~15-25s):
  -> Server is NOT being reused correctly
  -> Possible causes:
     1. Event loop mismatch (asyncio.run creates new loop each call)
     2. Server wrapper not cached properly
     3. Server crashes between calls

Fix options:
  1. Keep single event loop across calls (don't use asyncio.run)
  2. Detect loop change and migrate server connection
  3. Use subprocess-based server that survives loop changes
""")
            elif times[0] > 10000 and len(times) >= 2 and times[1] < 1000:
                print("""
[GOOD] Server reuse is working:
  -> Run 1 slow (server startup)
  -> Runs 2+ fast (server reused)

The server caching is working correctly.
If the agent is still slow, the issue is elsewhere
(e.g., lsp_manager being reset per call).
""")
            else:
                print(f"""
[INFO] Timings: {[f'{t:.0f}ms' for t in times]}
Check the detailed logs above for more information.
""")


if __name__ == "__main__":
    main()
