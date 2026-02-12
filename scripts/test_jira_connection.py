"""Test Jira connection via Atlassian Remote MCP Server.

Usage:
    python scripts/test_jira_connection.py

Prerequisites:
    - Node.js v18+ (for npx mcp-remote)
    - An Atlassian Cloud account with Jira

What happens:
    1. Checks that npx is available
    2. Launches `npx mcp-remote https://mcp.atlassian.com/v1/mcp`
    3. On first run, opens a browser for OAuth 2.1 login
    4. Discovers available MCP tools
    5. Invokes a read-only search query
"""

import asyncio
import json
import sys
from pathlib import Path

# Add project root to path
project_root = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(project_root))


def check_prerequisites():
    """Verify npx is available."""
    import shutil

    print("=" * 60)
    print("  Jira MCP Connection Test")
    print("=" * 60)
    print()

    npx = shutil.which("npx")
    if not npx:
        print("[FAIL] npx not found on PATH. Install Node.js v18+.")
        sys.exit(1)
    print(f"[OK] npx found: {npx}")

    # Check node version
    import subprocess
    result = subprocess.run(["node", "--version"], capture_output=True, text=True)
    if result.returncode == 0:
        version = result.stdout.strip()
        print(f"[OK] Node.js: {version}")
        major = int(version.lstrip("v").split(".")[0])
        if major < 18:
            print(f"[WARN] Node.js v18+ recommended, you have {version}")
    print()


async def test_connection():
    """Connect to Atlassian MCP via mcp-remote and discover tools."""
    from src.integrations.mcp.client import McpClient, StdioTransport, McpError
    from src.integrations.mcp.config import McpServerConfig
    from src.integrations.jira.connection import ATLASSIAN_MCP_URL

    print("-" * 60)
    print("  Step 1: Connect via mcp-remote (stdio transport)")
    print("-" * 60)
    print(f"  MCP URL: {ATLASSIAN_MCP_URL}")
    print(f"  Command: npx -y mcp-remote {ATLASSIAN_MCP_URL}")
    print()
    print("  If this is your first connection, a browser window will open")
    print("  for Atlassian OAuth login. Authorize the connection there.")
    print()

    config = McpServerConfig(
        name="atlassian-rovo-test",
        command=f"npx -y mcp-remote {ATLASSIAN_MCP_URL}",
        tool_prefix="jira",
        connect_timeout=120.0,  # Generous timeout for first OAuth flow
        invoke_timeout=60.0,
        discovery_timeout=30.0,
    )

    transport = StdioTransport()
    client = McpClient(config, transport)

    try:
        print("  Connecting (this may take a moment for npm download + OAuth)...")
        await client.connect()
        print("  [OK] Connected to Atlassian MCP server")
    except Exception as e:
        print(f"  [FAIL] Connection failed: {type(e).__name__}: {e}")
        # Check if there's stderr output
        if transport._process and transport._process.stderr:
            stderr = await transport._process.stderr.read()
            if stderr:
                print(f"  stderr: {stderr.decode()[:500]}")
        return None, None

    return client, transport


async def test_list_tools(client):
    """Discover available MCP tools."""
    print()
    print("-" * 60)
    print("  Step 2: Discover MCP Tools")
    print("-" * 60)

    try:
        tools = await client.list_tools()
        print(f"  [OK] Discovered {len(tools)} tools:")
        print()
        for tool in tools:
            name = tool.get("name", "?")
            desc = tool.get("description", "")
            # Truncate long descriptions
            if len(desc) > 80:
                desc = desc[:77] + "..."
            print(f"    {name}")
            print(f"      {desc}")
            # Show parameters
            schema = tool.get("inputSchema", {})
            props = schema.get("properties", {})
            required = schema.get("required", [])
            if props:
                param_list = []
                for pname, pschema in props.items():
                    ptype = pschema.get("type", "?")
                    req = "*" if pname in required else ""
                    param_list.append(f"{pname}{req}:{ptype}")
                print(f"      params: {', '.join(param_list)}")
            print()
        return tools
    except Exception as e:
        print(f"  [FAIL] {type(e).__name__}: {e}")
        return []


async def test_invoke_search(client, tools):
    """Try invoking a read-only search if available."""
    print("-" * 60)
    print("  Step 3: Invoke a Read-Only Tool")
    print("-" * 60)

    # Look for a search or list tool
    tool_names = [t.get("name", "") for t in tools]

    # Try common Jira tool names
    search_candidates = [
        "search_issues", "searchIssues", "jql_search",
        "list_projects", "listProjects", "get_projects",
    ]
    target_tool = None
    for candidate in search_candidates:
        if candidate in tool_names:
            target_tool = candidate
            break

    if not target_tool:
        # Just use the first tool that looks read-only
        print(f"  Available tools: {tool_names}")
        if tool_names:
            target_tool = tool_names[0]
            print(f"  No standard search tool found, trying: {target_tool}")
        else:
            print("  [SKIP] No tools available to test")
            return

    print(f"  Invoking: {target_tool}")

    # Build minimal arguments based on what we know
    args = {}
    tool_schema = next((t for t in tools if t.get("name") == target_tool), {})
    required = tool_schema.get("inputSchema", {}).get("required", [])
    props = tool_schema.get("inputSchema", {}).get("properties", {})

    # Try to fill required params with sensible defaults
    for param in required:
        ptype = props.get(param, {}).get("type", "string")
        if "jql" in param.lower():
            args[param] = "order by created DESC"
        elif "query" in param.lower():
            args[param] = "test"
        elif "project" in param.lower():
            args[param] = ""  # empty might list all
        elif ptype == "integer":
            args[param] = 5
        else:
            args[param] = ""

    print(f"  Arguments: {json.dumps(args, indent=2)}")

    try:
        result = await client.invoke(target_tool, args)
        is_error = result.get("isError", False)
        content = result.get("content", [])

        if is_error:
            print(f"  [ERROR] Tool returned error:")
            for block in content:
                print(f"    {block.get('text', json.dumps(block))[:300]}")
        else:
            print(f"  [OK] Got {len(content)} content block(s):")
            for block in content[:5]:
                btype = block.get("type", "?")
                if btype == "text":
                    text = block.get("text", "")
                    # Try to pretty-print JSON
                    try:
                        parsed = json.loads(text)
                        text = json.dumps(parsed, indent=2)[:500]
                    except (json.JSONDecodeError, TypeError):
                        text = text[:500]
                    print(f"    [{btype}] {text}")
                else:
                    print(f"    [{btype}] {json.dumps(block)[:300]}")

    except Exception as e:
        print(f"  [FAIL] {type(e).__name__}: {e}")


async def main():
    check_prerequisites()

    client, transport = await test_connection()
    if not client:
        sys.exit(1)

    try:
        tools = await test_list_tools(client)

        if tools:
            await test_invoke_search(client, tools)

        # Summary
        print()
        print("=" * 60)
        print("  Summary")
        print("=" * 60)
        print(f"  Transport:  stdio (mcp-remote)")
        print(f"  MCP tools:  {len(tools)} discovered")
        print(f"  Connection: OK")
        print()

    finally:
        try:
            await client.disconnect()
            print("[OK] Disconnected")
        except Exception:
            pass


if __name__ == "__main__":
    asyncio.run(main())
