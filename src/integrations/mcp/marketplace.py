"""MCP marketplace - browse and install MCP servers from the official registry.

Queries the official MCP registry (registry.modelcontextprotocol.io) to let
users discover, search, and one-click install MCP servers.

No API key required.
"""

import logging
from dataclasses import dataclass, field
from typing import Any

try:
    from src.observability import get_logger

    logger = get_logger("integrations.mcp.marketplace")
except ImportError:
    logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Registry URL
# ---------------------------------------------------------------------------

OFFICIAL_REGISTRY_BASE = "https://registry.modelcontextprotocol.io"
NPM_SEARCH_BASE = "https://registry.npmjs.org"


# ---------------------------------------------------------------------------
# Data models
# ---------------------------------------------------------------------------

@dataclass
class McpMarketplaceEntry:
    """A single MCP server from the marketplace."""

    # Identity
    id: str  # Official registry name (e.g. "io.github.owner/server-name")
    name: str  # Human-readable display name
    author: str
    description: str

    # Install info — stdio (local)
    transport: str = "stdio"  # "stdio", "sse", or "streamable-http"
    command: str | None = None  # e.g. "npx"
    args: list[str] = field(default_factory=list)  # e.g. ["-y", "@modelcontextprotocol/server-github"]
    env_vars: list[str] = field(default_factory=list)  # Required env var names

    # Install info — remote (hosted)
    remote_url: str = ""  # e.g. "https://mcp.atlassian.com/v1/sse"
    remote_headers: dict[str, str] = field(default_factory=dict)  # e.g. {"Authorization": "Bearer ..."}

    # Metadata
    tags: list[str] = field(default_factory=list)
    url: str = ""  # Project/homepage URL
    icon_url: str = ""  # Icon for UI display
    use_count: int = 0  # Popularity metric
    verified: bool = False
    is_remote: bool = False  # Has hosted/remote deployment option

    # Source registry
    source: str = "official"

    def to_dict(self) -> dict[str, Any]:
        """Serialize for API/UI consumption."""
        return {
            "id": self.id,
            "name": self.name,
            "author": self.author,
            "description": self.description,
            "transport": self.transport,
            "command": self.command,
            "args": self.args,
            "envVars": self.env_vars,
            "tags": self.tags,
            "url": self.url,
            "iconUrl": self.icon_url,
            "useCount": self.use_count,
            "verified": self.verified,
            "isRemote": self.is_remote,
            "source": self.source,
        }


@dataclass
class McpMarketplaceSearchResult:
    """Paginated search results from the marketplace."""

    entries: list[McpMarketplaceEntry]
    total_count: int = 0
    page: int = 1
    page_size: int = 20
    has_next: bool = False

    def to_dict(self) -> dict[str, Any]:
        return {
            "entries": [e.to_dict() for e in self.entries],
            "totalCount": self.total_count,
            "page": self.page,
            "pageSize": self.page_size,
            "hasNext": self.has_next,
        }


# ---------------------------------------------------------------------------
# Official registry parsing
# ---------------------------------------------------------------------------

def _parse_official_entry(raw: dict[str, Any]) -> McpMarketplaceEntry:
    """Parse a server entry from the official MCP registry."""
    server = raw.get("server", raw)

    name = server.get("name", "")
    # Official format: "io.github.owner/server-name"
    parts = name.rsplit("/", 1)
    short_name = parts[-1] if parts else name

    # Prefer title over derived name
    display_name = server.get("title") or short_name.replace("-", " ").replace("_", " ").title()

    # Extract author from name prefix or repository
    repo = server.get("repository", {})
    repo_url = repo.get("url", "")
    website_url = server.get("websiteUrl", "") or repo_url
    author = ""
    # Try name prefix: "com.atlassian/server" -> "atlassian"
    if "." in parts[0] if len(parts) > 1 else False:
        prefix_parts = parts[0].split(".")
        author = prefix_parts[-1] if len(prefix_parts) >= 2 else ""
    # Fall back to GitHub URL
    if not author and "github.com/" in repo_url:
        github_parts = repo_url.rstrip("/").split("/")
        if len(github_parts) >= 4:
            author = github_parts[-2]

    # Get install info from packages (stdio servers)
    packages = server.get("packages", [])
    command = None
    args = []
    env_vars = []
    transport = "stdio"

    for pkg in packages:
        registry_type = pkg.get("registryType", "")
        identifier = pkg.get("identifier", "")

        if registry_type == "npm" and identifier:
            command = "npx"
            args = ["-y", identifier]
            break

    # Get env vars from packages
    for pkg in packages:
        for env in pkg.get("environmentVariables", []):
            env_name = env.get("name", "")
            if env_name:
                env_vars.append(env_name)

    # Get remote info (hosted servers)
    remotes = server.get("remotes", [])
    remote_url = ""
    remote_headers: dict[str, str] = {}
    is_remote = bool(remotes)

    if remotes and not command:
        # No local package — this is a remote-only server
        # Prefer SSE over streamable-http (wider compatibility)
        remote = remotes[0]
        for r in remotes:
            if r.get("type") == "sse":
                remote = r
                break

        remote_url = remote.get("url", "")
        transport = remote.get("type", "sse")

        # Extract headers
        for header in remote.get("headers", []):
            header_name = header.get("name", "")
            header_value = header.get("value", "")
            if header_name:
                remote_headers[header_name] = header_value

    # Check official status from _meta
    meta = raw.get("_meta", {})
    official_meta = meta.get("io.modelcontextprotocol.registry/official", {})
    is_official = official_meta.get("status") == "active"

    # Version info
    version = server.get("version", "")

    return McpMarketplaceEntry(
        id=name,
        name=display_name,
        author=author,
        description=server.get("description", ""),
        transport=transport,
        command=command,
        args=args,
        env_vars=env_vars,
        remote_url=remote_url,
        remote_headers=remote_headers,
        url=website_url,
        verified=is_official,
        is_remote=is_remote,
        tags=[f"v{version}"] if version else [],
        source="official",
    )


# ---------------------------------------------------------------------------
# Marketplace client
# ---------------------------------------------------------------------------

class McpMarketplace:
    """Client for browsing and searching MCP servers.

    Primary: Official MCP Registry (registry.modelcontextprotocol.io).
    Secondary: npm registry (for popular servers not in official registry).
    """

    def __init__(self):
        self._http_client = None

    async def _get_client(self):
        """Lazy-init httpx client."""
        if self._http_client is None:
            import httpx

            self._http_client = httpx.AsyncClient(
                timeout=httpx.Timeout(connect=10, read=30, write=10, pool=10),
                follow_redirects=True,
            )
        return self._http_client

    async def close(self):
        """Close the HTTP client."""
        if self._http_client:
            await self._http_client.aclose()
            self._http_client = None

    # ------------------------------------------------------------------
    # Search
    # ------------------------------------------------------------------

    async def search(
        self,
        query: str = "",
        page: int = 1,
        page_size: int = 20,
    ) -> McpMarketplaceSearchResult:
        """Search for MCP servers.

        Queries the official registry, plus a direct npm lookup for the
        @modelcontextprotocol/server-{query} package (in parallel).

        Args:
            query: Search query (empty = browse all).
            page: Page number (1-indexed).
            page_size: Results per page.

        Returns:
            McpMarketplaceSearchResult with matching entries.
        """
        import asyncio

        # Query official registry + direct npm lookup in parallel
        official_task = asyncio.create_task(self._search_official_safe(query, page, page_size))
        npm_task = asyncio.create_task(self._lookup_mcp_official_package(query)) if query else None

        official_result = await official_task
        npm_entry = await npm_task if npm_task else None

        # Merge: npm official package first (if found and not already in results)
        merged: list[McpMarketplaceEntry] = []
        seen_names: set[str] = set()

        if npm_entry:
            # Check it's not already in official results
            official_names = {e.name.lower() for e in official_result.entries}
            official_ids = {e.id.lower() for e in official_result.entries}
            if npm_entry.name.lower() not in official_names and npm_entry.id.lower() not in official_ids:
                merged.append(npm_entry)
                seen_names.add(npm_entry.name.lower())

        for entry in official_result.entries:
            if entry.name.lower() not in seen_names:
                seen_names.add(entry.name.lower())
                merged.append(entry)

        return McpMarketplaceSearchResult(
            entries=merged,
            total_count=len(merged),
            page=page,
            page_size=page_size,
            has_next=official_result.has_next,
        )

    async def _search_official_safe(
        self, query: str, page: int, page_size: int
    ) -> McpMarketplaceSearchResult:
        """Search official registry, returning empty on failure."""
        try:
            return await self._search_official(query, page, page_size)
        except Exception as e:
            logger.warning("mcp_registry_search_failed", error=str(e), query=query)
            return McpMarketplaceSearchResult(entries=[], total_count=0, page=page, page_size=page_size)

    async def _lookup_mcp_official_package(self, query: str) -> McpMarketplaceEntry | None:
        """Direct npm lookup for @modelcontextprotocol/server-{query}.

        The MCP team publishes official servers under this naming convention.
        npm search doesn't surface them reliably, so we do a direct lookup.
        Returns None if the package doesn't exist (404).
        """
        try:
            client = await self._get_client()
            # Normalize query to package name format
            pkg_suffix = query.strip().lower().replace(" ", "-")
            pkg_name = f"@modelcontextprotocol/server-{pkg_suffix}"

            response = await client.get(f"{NPM_SEARCH_BASE}/{pkg_name}")
            if response.status_code == 404:
                return None
            response.raise_for_status()
            data = response.json()

            description = data.get("description", "")
            latest_version = data.get("dist-tags", {}).get("latest", "")
            repo = data.get("repository", {})
            repo_url = repo.get("url", "") if isinstance(repo, dict) else ""
            # Clean up git+https:// prefix
            if repo_url.startswith("git+"):
                repo_url = repo_url[4:]
            if repo_url.endswith(".git"):
                repo_url = repo_url[:-4]

            return McpMarketplaceEntry(
                id=f"npm:{pkg_name}",
                name=pkg_name,
                author="modelcontextprotocol",
                description=description,
                transport="stdio",
                command="npx",
                args=["-y", pkg_name],
                url=repo_url,
                verified=True,  # Official MCP team package
                tags=[f"v{latest_version}"] if latest_version else [],
                source="npm",
            )
        except Exception as e:
            logger.debug("mcp_official_npm_lookup_failed", query=query, error=str(e))
            return None

    async def get_server_detail(self, server_id: str) -> McpMarketplaceEntry | None:
        """Get detailed info for a specific server.

        Handles both official registry IDs and npm package IDs (prefixed with 'npm:').

        Args:
            server_id: Official registry name or "npm:@scope/package-name".

        Returns:
            McpMarketplaceEntry with full details, or None if not found.
        """
        try:
            if server_id.startswith("npm:"):
                # npm package — construct entry from package name
                pkg_name = server_id[4:]  # strip "npm:" prefix
                return McpMarketplaceEntry(
                    id=server_id,
                    name=pkg_name,
                    author="",
                    description="",
                    transport="stdio",
                    command="npx",
                    args=["-y", pkg_name],
                    source="npm",
                )
            return await self._get_official_detail(server_id)
        except Exception as e:
            logger.warning("mcp_registry_detail_failed", server_id=server_id, error=str(e))
            return None

    # ------------------------------------------------------------------
    # Official registry implementation
    # ------------------------------------------------------------------

    async def _search_official(
        self, query: str, page: int, page_size: int
    ) -> McpMarketplaceSearchResult:
        """Search official MCP registry.

        Uses cursor-based pagination. For page > 1, we make sequential
        requests following nextCursor to reach the desired page.
        """
        client = await self._get_client()

        params: dict[str, Any] = {"limit": page_size}
        if query:
            params["search"] = query

        # For page 1, just fetch directly. For later pages, follow cursors.
        cursor = None
        for _ in range(page - 1):
            # Fetch previous pages to get the cursor for the target page
            response = await client.get(
                f"{OFFICIAL_REGISTRY_BASE}/v0/servers",
                params={**params, **({"cursor": cursor} if cursor else {})},
            )
            response.raise_for_status()
            data = response.json()
            cursor = data.get("metadata", {}).get("nextCursor")
            if cursor is None:
                # No more pages
                return McpMarketplaceSearchResult(
                    entries=[], total_count=0, page=page, page_size=page_size
                )

        # Fetch the target page
        if cursor:
            params["cursor"] = cursor

        response = await client.get(
            f"{OFFICIAL_REGISTRY_BASE}/v0/servers", params=params
        )
        response.raise_for_status()
        data = response.json()

        servers = data.get("servers", [])
        metadata = data.get("metadata", {})

        # Deduplicate: the API returns multiple versions of the same server.
        # Keep only the first occurrence (latest version) per server name.
        seen_names: set[str] = set()
        entries: list[McpMarketplaceEntry] = []
        for s in servers:
            entry = _parse_official_entry(s)
            if entry.id not in seen_names:
                seen_names.add(entry.id)
                entries.append(entry)

        has_next = metadata.get("nextCursor") is not None

        return McpMarketplaceSearchResult(
            entries=entries,
            total_count=len(entries),
            page=page,
            page_size=page_size,
            has_next=has_next,
        )

    async def _get_official_detail(self, server_id: str) -> McpMarketplaceEntry | None:
        """Get detailed server info from the official registry.

        The list endpoint returns enough detail, so we search by name.
        """
        client = await self._get_client()

        response = await client.get(
            f"{OFFICIAL_REGISTRY_BASE}/v0/servers",
            params={"search": server_id, "limit": 5},
        )
        response.raise_for_status()
        data = response.json()

        # Find exact match by name
        for raw in data.get("servers", []):
            server = raw.get("server", {})
            if server.get("name") == server_id:
                return _parse_official_entry(raw)

        # Fallback: return first result if any
        servers = data.get("servers", [])
        if servers:
            return _parse_official_entry(servers[0])

        return None

    # ------------------------------------------------------------------
    # npm registry (secondary source for popular servers)
    # ------------------------------------------------------------------

    # ------------------------------------------------------------------
    # Install helper
    # ------------------------------------------------------------------

    def create_install_config(
        self,
        entry: McpMarketplaceEntry,
        env_values: dict[str, str] | None = None,
    ) -> dict[str, Any] | None:
        """Generate mcp_settings.json server config from a marketplace entry.

        Args:
            entry: The marketplace entry to install.
            env_values: Values for required environment variables.

        Returns:
            Dict ready to insert into mcp_settings.json, or None if the
            server has no usable install info (manual setup required).
        """
        # Generate toolPrefix from entry ID (strip "npm:" prefix, sanitize)
        import re
        clean_id = entry.id.split(":", 1)[-1] if ":" in entry.id else entry.id
        prefix = re.sub(r"[^a-zA-Z0-9_-]", "_", clean_id)
        config: dict[str, Any] = {
            "enabled": True,
            "toolPrefix": prefix,
        }

        if entry.command:
            # Stdio server (local subprocess)
            config["command"] = entry.command
            if entry.args:
                config["args"] = list(entry.args)
            if entry.env_vars and env_values:
                config["env"] = {k: env_values.get(k, "") for k in entry.env_vars}
        elif entry.remote_url:
            # Remote server — use mcp-remote bridge to wrap as stdio
            # mcp-remote handles SSE/HTTP connection and exposes it as stdio JSON-RPC
            config["command"] = "npx"
            config["args"] = ["-y", "mcp-remote@latest", entry.remote_url]
        else:
            # No install info — can't auto-install
            return None

        return config
