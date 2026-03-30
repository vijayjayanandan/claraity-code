"""Test Jira connection via mcp-atlassian MCP server.

Usage:
    python scripts/test_jira_connection.py <profile>

    e.g.  python scripts/test_jira_connection.py personal
          python scripts/test_jira_connection.py corporate

Prerequisites:
    - uv / uvx installed (Python package manager)
    - A Jira profile configured in .claraity/integrations/jira/<profile>.json

What happens:
    1. Loads the named profile config
    2. Launches `uvx mcp-atlassian` with API token env vars
    3. Discovers available MCP tools
    4. Invokes a read-only search query
"""

import asyncio
import json
import sys
from pathlib import Path

# Add project root to path
project_root = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(project_root))


def check_prerequisites():
    """Verify uvx is available."""
    import shutil

    print("=" * 60)
    print("  Jira MCP Connection Test (mcp-atlassian)")
    print("=" * 60)
    print()

    uvx = shutil.which("uvx")
    if not uvx:
        print("[FAIL] uvx not found on PATH. Install uv: https://docs.astral.sh/uv/")
        sys.exit(1)
    print(f"[OK] uvx found: {uvx}")
    print()


async def test_connection(profile: str):
    """Connect to Jira via mcp-atlassian and discover tools."""
    from src.integrations.mcp.client import McpClient, StdioTransport
    from src.integrations.jira.connection import JiraConnection

    conn = JiraConnection(profile=profile)
    if not conn.is_configured():
        print(f"[FAIL] Profile '{profile}' not configured.")
        print(f"       Edit .claraity/integrations/jira/{profile}.json")
        sys.exit(1)

    config = conn.get_mcp_config()

    print("-" * 60)
    print("  Step 1: Connect via mcp-atlassian (stdio transport)")
    print("-" * 60)
    print(f"  Profile:  {profile}")
    print(f"  Jira URL: {conn.jira_url}")
    print(f"  Username: {conn.username}")
    print(f"  Command:  {config.command}")
    print()

    transport = StdioTransport()
    client = McpClient(config, transport)

    try:
        print("  Connecting...")
        await client.connect()
        print("  [OK] Connected to mcp-atlassian")
    except Exception as e:
        print(f"  [FAIL] Connection failed: {type(e).__name__}: {e}")
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
            if len(desc) > 80:
                desc = desc[:77] + "..."
            print(f"    {name}")
            print(f"      {desc}")
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

    tool_names = [t.get("name", "") for t in tools]

    search_candidates = [
        "search_issues", "searchIssues", "jql_search",
        "jira_search", "list_projects", "listProjects",
    ]
    target_tool = None
    for candidate in search_candidates:
        if candidate in tool_names:
            target_tool = candidate
            break

    if not target_tool:
        print(f"  Available tools: {tool_names}")
        if tool_names:
            target_tool = tool_names[0]
            print(f"  No standard search tool found, trying: {target_tool}")
        else:
            print("  [SKIP] No tools available to test")
            return

    print(f"  Invoking: {target_tool}")

    args = {}
    tool_schema = next((t for t in tools if t.get("name") == target_tool), {})
    required = tool_schema.get("inputSchema", {}).get("required", [])
    props = tool_schema.get("inputSchema", {}).get("properties", {})

    for param in required:
        ptype = props.get(param, {}).get("type", "string")
        if "jql" in param.lower():
            args[param] = "order by created DESC"
        elif "query" in param.lower():
            args[param] = "test"
        elif "project" in param.lower():
            args[param] = ""
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
    if len(sys.argv) < 2:
        # List available profiles
        from src.integrations.jira.connection import JiraConnection
        profiles = JiraConnection.list_profiles()
        if profiles:
            print(f"Available profiles: {', '.join(profiles)}")
            print(f"Usage: python scripts/test_jira_connection.py <profile>")
        else:
            print("No Jira profiles configured.")
            print("Create one at .claraity/integrations/jira/<profile>.json")
        sys.exit(1)

    profile = sys.argv[1]
    check_prerequisites()

    client, transport = await test_connection(profile)
    if not client:
        sys.exit(1)

    try:
        tools = await test_list_tools(client)

        if tools:
            await test_invoke_search(client, tools)

        print()
        print("=" * 60)
        print("  Summary")
        print("=" * 60)
        print(f"  Profile:    {profile}")
        print(f"  Transport:  stdio (uvx mcp-atlassian)")
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
