"""MCP settings manager - file-based configuration for MCP servers.

Loads/saves .claraity/mcp_settings.json which stores:
- Server definitions (transport, command, args, env, enabled)
- Per-tool visibility overrides (enabled/disabled per tool)

On discovery, new tools are merged into the saved config with enabled=True.
Users can then toggle individual tools off to hide them from the LLM.
"""

import json
import logging
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from .config import McpServerConfig

try:
    from src.observability import get_logger

    logger = get_logger("integrations.mcp.settings")
except ImportError:
    logger = logging.getLogger(__name__)


# Settings file locations
DEFAULT_PROJECT_PATH = Path(".claraity") / "mcp_settings.json"
DEFAULT_GLOBAL_PATH = Path.home() / ".claraity" / "mcp_settings.json"


@dataclass
class McpToolOverride:
    """Per-tool visibility override from user config."""

    enabled: bool = True

    def to_dict(self) -> dict[str, Any]:
        return {"enabled": self.enabled}

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "McpToolOverride":
        return cls(enabled=data.get("enabled", True))


@dataclass
class McpServerSettings:
    """User-facing settings for a single MCP server.

    This is the serializable config that lives in mcp_settings.json.
    It maps to McpServerConfig for the runtime layer.
    """

    # Server identity
    name: str

    # Transport config — inferred from fields present:
    #   command/args → stdio (local subprocess)
    #   url          → remote (SSE/HTTP)
    transport: str = "stdio"  # "stdio", "sse", or "streamable-http"
    command: str | None = None  # For stdio: e.g. "npx"
    args: list[str] = field(default_factory=list)  # For stdio: e.g. ["-y", "@modelcontextprotocol/server-github"]
    server_url: str | None = None  # For remote: e.g. "https://mcp.atlassian.com/v1/sse"
    headers: dict[str, str] = field(default_factory=dict)  # For remote: auth headers
    env: dict[str, str] = field(default_factory=dict)  # Environment variables (stdio)

    # Server-level toggle
    enabled: bool = True

    # Namespacing
    tool_prefix: str = ""

    # Per-tool overrides: { "tool_name": { "enabled": true/false } }
    # Keys are the RAW MCP tool names (without prefix)
    tools: dict[str, McpToolOverride] = field(default_factory=dict)

    # NOTE: env values are stored in plaintext in mcp_settings.json.
    # The file lives under .claraity/ which is gitignored by default.
    # For sensitive tokens, prefer referencing env vars by name
    # (e.g. set GITHUB_TOKEN in your shell, not in this file).

    # Timeouts
    connect_timeout: float = 30.0
    invoke_timeout: float = 60.0

    # Result limits
    max_result_chars: int = 8192

    @property
    def is_remote(self) -> bool:
        """True if this is a remote (URL-based) server, not a local subprocess."""
        return self.server_url is not None and self.command is None

    def to_dict(self) -> dict[str, Any]:
        """Serialize for JSON storage.

        Follows industry standard: presence of 'command' vs 'url' determines transport.
        """
        d: dict[str, Any] = {
            "enabled": self.enabled,
        }
        if self.server_url and not self.command:
            # Remote server — url + optional headers
            d["url"] = self.server_url
            if self.headers:
                d["headers"] = self.headers
        else:
            # Local stdio server — command + args + env
            if self.command:
                d["command"] = self.command
            if self.args:
                d["args"] = self.args
            if self.env:
                d["env"] = self.env
        d["toolPrefix"] = self.tool_prefix
        if self.tools:
            d["tools"] = {name: override.to_dict() for name, override in self.tools.items()}
        if self.connect_timeout != 30.0:
            d["connectTimeout"] = self.connect_timeout
        if self.invoke_timeout != 60.0:
            d["invokeTimeout"] = self.invoke_timeout
        if self.max_result_chars != 8192:
            d["maxResultChars"] = self.max_result_chars
        return d

    @classmethod
    def from_dict(cls, name: str, data: dict[str, Any]) -> "McpServerSettings":
        """Deserialize from JSON config.

        Supports industry standard format: 'url' field = remote, 'command' field = stdio.
        Also supports legacy 'serverUrl' and explicit 'transport' fields.
        """
        tools_raw = data.get("tools", {})
        tools = {
            tool_name: McpToolOverride.from_dict(tool_data) if isinstance(tool_data, dict) else McpToolOverride(enabled=bool(tool_data))
            for tool_name, tool_data in tools_raw.items()
        }

        command = data.get("command")
        args = data.get("args", [])
        # Support both 'url' (industry standard) and 'serverUrl' (legacy)
        server_url = data.get("url") or data.get("serverUrl")
        headers = data.get("headers", {})

        # Infer transport from fields present
        if data.get("transport"):
            transport = data["transport"]
        elif server_url and not command:
            transport = "sse"  # remote server
        else:
            transport = "stdio"

        return cls(
            name=name,
            transport=transport,
            command=command,
            args=args,
            server_url=server_url,
            headers=headers,
            env=data.get("env", {}),
            enabled=data.get("enabled", True),
            tool_prefix=data.get("toolPrefix", name),
            tools=tools,
            connect_timeout=data.get("connectTimeout", 30.0),
            invoke_timeout=data.get("invokeTimeout", 60.0),
            max_result_chars=data.get("maxResultChars", 8192),
        )

    def to_runtime_config(self) -> McpServerConfig:
        """Convert to runtime McpServerConfig for the MCP client layer.

        For stdio transport, combines command + args into a single command string.
        """
        if self.transport == "stdio" and self.command:
            # Build full command with args for the StdioTransport
            import sys
            parts = [self.command] + self.args
            if sys.platform == "win32":
                import subprocess
                full_command = subprocess.list2cmdline(parts)
            else:
                import shlex
                full_command = " ".join(shlex.quote(p) for p in parts)
        else:
            full_command = self.command

        return McpServerConfig(
            name=self.name,
            server_url=self.server_url,
            command=full_command,
            connect_timeout=self.connect_timeout,
            invoke_timeout=self.invoke_timeout,
            max_result_chars=self.max_result_chars,
            extra_env=dict(self.env),
            extra_headers=dict(self.headers),
            tool_prefix=self.tool_prefix or self.name,
        )

    def get_disabled_tools(self) -> set[str]:
        """Return set of raw MCP tool names that are disabled."""
        return {name for name, override in self.tools.items() if not override.enabled}

    def is_tool_enabled(self, raw_tool_name: str) -> bool:
        """Check if a specific tool is enabled.

        Tools not yet in the config are enabled by default (new tools from server).
        """
        override = self.tools.get(raw_tool_name)
        if override is None:
            return True  # New tools default to enabled
        return override.enabled

    def merge_discovered_tools(self, discovered_tool_names: list[str]) -> list[str]:
        """Merge discovered tools with saved config.

        New tools (not in config) are added with enabled=True.
        Existing tools keep their saved enabled/disabled state.
        Tools in config but NOT in discovered list are kept (server may be down).

        Args:
            discovered_tool_names: Raw MCP tool names from tools/list.

        Returns:
            List of newly discovered tool names (not previously in config).
        """
        new_tools = []
        for tool_name in discovered_tool_names:
            if tool_name not in self.tools:
                self.tools[tool_name] = McpToolOverride(enabled=True)
                new_tools.append(tool_name)

        if new_tools:
            logger.info(
                "mcp_new_tools_discovered",
                server=self.name,
                new_tools=new_tools,
                count=len(new_tools),
            )

        return new_tools


class McpSettingsManager:
    """Manages MCP settings across project and global scope.

    Two config files, merged at load time:
    - Project: .claraity/mcp_settings.json (per-project, team-shared)
    - Global:  ~/.claraity/mcp_settings.json (personal, all projects)

    Merge rule: both files' servers are combined. If the same server name
    exists in both, the project config wins.

    Writes always go to a specific scope (project or global).
    """

    def __init__(
        self,
        project_path: Path | None = None,
        global_path: Path | None = None,
        settings_path: Path | None = None,  # Legacy: treated as project path
    ):
        self._project_path = project_path or settings_path or DEFAULT_PROJECT_PATH
        self._global_path = global_path or DEFAULT_GLOBAL_PATH
        self._servers: dict[str, McpServerSettings] = {}
        self._server_scopes: dict[str, str] = {}  # server_name -> "project" | "global"
        self._loaded = False

    @property
    def project_path(self) -> Path:
        return self._project_path

    @property
    def global_path(self) -> Path:
        return self._global_path

    @property
    def settings_path(self) -> Path:
        """Legacy: returns project path."""
        return self._project_path

    @property
    def servers(self) -> dict[str, McpServerSettings]:
        """All configured servers (merged, read-only view)."""
        return dict(self._servers)

    def get_scope(self, server_name: str) -> str:
        """Get the scope ('project' or 'global') for a server."""
        return self._server_scopes.get(server_name, "project")

    def _load_file(self, path: Path) -> dict[str, McpServerSettings]:
        """Load servers from a single config file."""
        if not path.exists():
            return {}
        try:
            raw = json.loads(path.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, OSError) as e:
            logger.error("mcp_settings_load_error", path=str(path), error=str(e))
            return {}
        servers_raw = raw.get("mcpServers", {})
        return {
            name: McpServerSettings.from_dict(name, data)
            for name, data in servers_raw.items()
        }

    def load(self) -> None:
        """Load and merge settings from both project and global files.

        Global servers are loaded first, then project servers override
        any with the same name.
        """
        global_servers = self._load_file(self._global_path)
        project_servers = self._load_file(self._project_path)

        # Merge: global first, project overrides
        self._servers = {}
        self._server_scopes = {}

        for name, server in global_servers.items():
            self._servers[name] = server
            self._server_scopes[name] = "global"

        for name, server in project_servers.items():
            self._servers[name] = server
            self._server_scopes[name] = "project"

        logger.info(
            "mcp_settings_loaded",
            project_path=str(self._project_path),
            global_path=str(self._global_path),
            project_count=len(project_servers),
            global_count=len(global_servers),
            merged_count=len(self._servers),
        )
        self._loaded = True

    def _save_file(self, path: Path, servers: dict[str, McpServerSettings]) -> None:
        """Save servers to a specific config file (atomic write)."""
        path.parent.mkdir(parents=True, exist_ok=True)
        data = {
            "mcpServers": {
                name: server.to_dict()
                for name, server in servers.items()
            }
        }
        content = json.dumps(data, indent=2, ensure_ascii=False) + "\n"
        tmp_path = path.with_suffix(".tmp")
        tmp_path.write_text(content, encoding="utf-8")
        tmp_path.replace(path)

    def save(self) -> None:
        """Save all servers back to their respective scope files."""
        project_servers: dict[str, McpServerSettings] = {}
        global_servers: dict[str, McpServerSettings] = {}

        for name, server in self._servers.items():
            scope = self._server_scopes.get(name, "project")
            if scope == "global":
                global_servers[name] = server
            else:
                project_servers[name] = server

        # Only write a scope file if it has servers or already exists
        if project_servers or self._project_path.exists():
            self._save_file(self._project_path, project_servers)
        if global_servers or self._global_path.exists():
            self._save_file(self._global_path, global_servers)

        logger.info(
            "mcp_settings_saved",
            project_count=len(project_servers),
            global_count=len(global_servers),
        )

    def get_server(self, name: str) -> McpServerSettings | None:
        """Get settings for a specific server."""
        return self._servers.get(name)

    def add_server(self, settings: McpServerSettings, scope: str = "project") -> None:
        """Add or update a server configuration.

        Args:
            settings: Server settings to add.
            scope: 'project' or 'global'.
        """
        self._servers[settings.name] = settings
        self._server_scopes[settings.name] = scope
        logger.info("mcp_server_added", server=settings.name, scope=scope)

    def remove_server(self, name: str) -> McpServerSettings | None:
        """Remove a server configuration. Returns removed settings or None."""
        removed = self._servers.pop(name, None)
        self._server_scopes.pop(name, None)
        if removed:
            logger.info("mcp_server_removed", server=name)
        return removed

    def get_enabled_servers(self) -> list[McpServerSettings]:
        """Return all servers that are enabled."""
        return [s for s in self._servers.values() if s.enabled]

    def update_tool_visibility(self, server_name: str, tool_name: str, enabled: bool) -> bool:
        """Toggle a specific tool's visibility for a server.

        Args:
            server_name: Server identifier.
            tool_name: Raw MCP tool name (without prefix).
            enabled: Whether the tool should be visible to the LLM.

        Returns:
            True if the update was applied, False if server not found.
        """
        server = self._servers.get(server_name)
        if server is None:
            return False

        server.tools[tool_name] = McpToolOverride(enabled=enabled)
        logger.info(
            "mcp_tool_visibility_changed",
            server=server_name,
            tool=tool_name,
            enabled=enabled,
        )
        return True

    def update_server_enabled(self, server_name: str, enabled: bool) -> bool:
        """Toggle a server's enabled state.

        Args:
            server_name: Server identifier.
            enabled: Whether the server should be connected.

        Returns:
            True if updated, False if server not found.
        """
        server = self._servers.get(server_name)
        if server is None:
            return False

        server.enabled = enabled
        logger.info("mcp_server_enabled_changed", server=server_name, enabled=enabled)
        return True

    def merge_discovered_tools(self, server_name: str, tool_names: list[str]) -> list[str]:
        """Merge discovered tools into a server's config.

        New tools get enabled=True by default. Existing tools keep their state.

        Args:
            server_name: Server identifier.
            tool_names: Raw MCP tool names from discovery.

        Returns:
            List of newly discovered tool names.
        """
        server = self._servers.get(server_name)
        if server is None:
            return []

        return server.merge_discovered_tools(tool_names)

    def get_tool_filter(self, server_name: str) -> set[str]:
        """Get the set of disabled tool names for a server.

        Used by McpToolRegistry to skip disabled tools during registration.

        Args:
            server_name: Server identifier.

        Returns:
            Set of raw MCP tool names that should NOT be registered.
        """
        server = self._servers.get(server_name)
        if server is None:
            return set()

        return server.get_disabled_tools()
