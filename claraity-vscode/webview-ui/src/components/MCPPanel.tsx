/**
 * MCP server management panel.
 *
 * Two tabs:
 * - Installed: shows connected servers with per-tool toggles
 * - Marketplace: search and install MCP servers from official registry + npm
 */
import { useState, useEffect, useCallback } from "react";
import type { WebViewMessage, McpServerInfo, McpMarketplaceEntry } from "../types";

interface MCPPanelProps {
  postMessage: (msg: WebViewMessage) => void;
  onBack: () => void;
  servers: McpServerInfo[];
  marketplace: McpMarketplaceEntry[];
  marketplaceMeta: { totalCount: number; page: number; hasNext: boolean } | null;
  notification: { message: string; success: boolean } | null;
}

type Tab = "installed" | "marketplace";

export function MCPPanel({
  postMessage,
  onBack,
  servers,
  marketplace,
  marketplaceMeta,
  notification,
}: MCPPanelProps) {
  const [activeTab, setActiveTab] = useState<Tab>("installed");
  const [searchQuery, setSearchQuery] = useState("");
  const [expandedServer, setExpandedServer] = useState<string | null>(null);
  const [searching, setSearching] = useState(false);

  // Request server list on mount
  useEffect(() => {
    postMessage({ type: "getMcpServers" });
  }, [postMessage]);

  // Auto-dismiss notification by refreshing server list (which clears stale notification)
  useEffect(() => {
    if (notification) {
      const timer = setTimeout(() => {
        postMessage({ type: "getMcpServers" });
      }, 5000);
      return () => clearTimeout(timer);
    }
  }, [notification, postMessage]);

  const handleSearch = useCallback(() => {
    setSearching(true);
    postMessage({ type: "mcpMarketplaceSearch", query: searchQuery, page: 1 });
    // searching flag cleared when results arrive
  }, [postMessage, searchQuery]);

  const handleSearchKeyDown = useCallback(
    (e: React.KeyboardEvent) => {
      if (e.key === "Enter") handleSearch();
    },
    [handleSearch],
  );

  // Clear searching when results arrive
  useEffect(() => {
    if (marketplace.length > 0 || marketplaceMeta) {
      setSearching(false);
    }
  }, [marketplace, marketplaceMeta]);

  const handleLoadMore = useCallback(() => {
    const nextPage = (marketplaceMeta?.page ?? 0) + 1;
    postMessage({ type: "mcpMarketplaceSearch", query: searchQuery, page: nextPage });
  }, [postMessage, searchQuery, marketplaceMeta]);

  const handleInstall = useCallback(
    (entry: McpMarketplaceEntry, scope: "project" | "global") => {
      postMessage({ type: "mcpInstall", serverId: entry.id, name: entry.name, scope });
    },
    [postMessage],
  );

  const handleUninstall = useCallback(
    (serverName: string) => {
      postMessage({ type: "mcpUninstall", serverName });
    },
    [postMessage],
  );

  const handleToggleServer = useCallback(
    (serverName: string, enabled: boolean) => {
      postMessage({ type: "mcpToggleServer", serverName, enabled });
    },
    [postMessage],
  );

  const handleSaveTools = useCallback(
    (serverName: string, toolStates: Record<string, boolean>) => {
      postMessage({ type: "mcpSaveTools", serverName, tools: toolStates });
    },
    [postMessage],
  );

  const handleReconnect = useCallback(
    (serverName: string) => {
      postMessage({ type: "mcpReconnect", serverName });
    },
    [postMessage],
  );

  const handleOpenDocs = useCallback(
    (url: string) => {
      postMessage({ type: "mcpOpenDocs", url });
    },
    [postMessage],
  );

  // Browse marketplace on first tab switch
  const handleTabSwitch = useCallback(
    (tab: Tab) => {
      setActiveTab(tab);
      if (tab === "marketplace" && marketplace.length === 0 && !searching) {
        setSearching(true);
        postMessage({ type: "mcpMarketplaceSearch", query: "", page: 1 });
      }
    },
    [postMessage, marketplace.length, searching],
  );

  return (
    <div className="mcp-panel">
      {/* Header */}
      <div className="panel-header">
        <button className="panel-back" onClick={onBack} title="Back to chat" aria-label="Back to chat">
          <i className="codicon codicon-arrow-left" />
        </button>
        <span className="panel-title">MCP Servers</span>
        <button
          className="mcp-icon-btn"
          onClick={() => postMessage({ type: "mcpOpenConfig", scope: "project" })}
          title="Edit project settings (.claraity/mcp_settings.json)"
          aria-label="Edit project MCP settings"
        >
          <i className="codicon codicon-file" />
        </button>
        <button
          className="mcp-icon-btn"
          onClick={() => postMessage({ type: "mcpOpenConfig", scope: "global" })}
          title="Edit global settings (~/.claraity/mcp_settings.json)"
          aria-label="Edit global MCP settings"
        >
          <i className="codicon codicon-globe" />
        </button>
        <button
          className="mcp-icon-btn"
          onClick={() => postMessage({ type: "mcpReload" })}
          title="Reload settings from disk and reconnect"
          aria-label="Reload MCP settings"
        >
          <i className="codicon codicon-refresh" />
        </button>
      </div>

      {/* Notification */}
      {notification && (
        <div className={`mcp-notification ${notification.success ? "success" : "error"}`}>
          {notification.message}
        </div>
      )}

      {/* Tabs */}
      <div className="mcp-tabs" role="tablist">
        <button
          className={`mcp-tab ${activeTab === "installed" ? "active" : ""}`}
          role="tab"
          aria-selected={activeTab === "installed"}
          onClick={() => handleTabSwitch("installed")}
        >
          Installed ({servers.length})
        </button>
        <button
          className={`mcp-tab ${activeTab === "marketplace" ? "active" : ""}`}
          role="tab"
          aria-selected={activeTab === "marketplace"}
          onClick={() => handleTabSwitch("marketplace")}
        >
          Marketplace
        </button>
      </div>

      {/* Installed tab */}
      {activeTab === "installed" && (
        <div className="mcp-installed">
          {servers.length === 0 ? (
            <div className="mcp-empty">
              <p>No MCP servers configured.</p>
              <p className="mcp-hint">
                Browse the <button className="link-button" onClick={() => handleTabSwitch("marketplace")}>Marketplace</button> to add servers,
                or edit <code>.claraity/mcp_settings.json</code> directly.
              </p>
            </div>
          ) : (
            <div className="mcp-server-list">
              {servers.map((server) => (
                <ServerCard
                  key={server.name}
                  server={server}
                  expanded={expandedServer === server.name}
                  onToggleExpand={() =>
                    setExpandedServer(expandedServer === server.name ? null : server.name)
                  }
                  onToggleServer={handleToggleServer}
                  onSaveTools={handleSaveTools}
                  onReconnect={handleReconnect}
                  onOpenDocs={handleOpenDocs}
                  onUninstall={handleUninstall}
                />
              ))}
            </div>
          )}
        </div>
      )}

      {/* Marketplace tab */}
      {activeTab === "marketplace" && (
        <div className="mcp-marketplace">
          <div className="mcp-search">
            <input
              type="text"
              className="mcp-search-input"
              placeholder="Search MCP servers..."
              value={searchQuery}
              onChange={(e) => setSearchQuery(e.target.value)}
              onKeyDown={handleSearchKeyDown}
            />
            <button className="mcp-search-btn" onClick={handleSearch} disabled={searching}>
              <i className="codicon codicon-search" />
            </button>
          </div>

          {searching && marketplace.length === 0 && (
            <div className="mcp-loading">Searching...</div>
          )}

          <div className="mcp-marketplace-list">
            {marketplace.map((entry) => {
              // Check if already installed by matching name, id, or display name
              const nameLower = entry.name.toLowerCase();
              const idLower = entry.id.toLowerCase();
              const installed = servers.some((s) => {
                const sLower = s.name.toLowerCase();
                return sLower === nameLower
                  || sLower === idLower
                  || sLower === idLower.replace("/", "-")
                  || sLower === nameLower.replace("/", "-");
              });
              return (
                <MarketplaceCard
                  key={entry.id}
                  entry={entry}
                  installed={installed}
                  onInstall={(scope) => handleInstall(entry, scope)}
                />
              );
            })}
          </div>

          {marketplaceMeta?.hasNext && (
            <button className="mcp-load-more" onClick={handleLoadMore}>
              Load more
            </button>
          )}

          {marketplaceMeta && (
            <div className="mcp-meta">
              Showing {marketplace.length} servers
              {(() => {
                const sources = new Set(marketplace.map((e) => e.source));
                const labels = [...sources].map((s) => s === "npm" ? "npm" : "Official Registry");
                return <> &middot; Source: {labels.join(" + ")}</>;
              })()}
            </div>
          )}
        </div>
      )}
    </div>
  );
}

// ---------------------------------------------------------------------------
// Server card (installed tab)
// ---------------------------------------------------------------------------

function ServerCard({
  server,
  expanded,
  onToggleExpand,
  onToggleServer,
  onSaveTools,
  onReconnect,
  onOpenDocs,
  onUninstall,
}: {
  server: McpServerInfo;
  expanded: boolean;
  onToggleExpand: () => void;
  onToggleServer: (name: string, enabled: boolean) => void;
  onSaveTools: (server: string, tools: Record<string, boolean>) => void;
  onReconnect: (name: string) => void;
  onOpenDocs: (url: string) => void;
  onUninstall: (name: string) => void;
}) {
  // Local tool toggle state — changes don't send to server until Save
  const [localTools, setLocalTools] = useState<Record<string, boolean>>(() =>
    Object.fromEntries(server.tools.map((t) => [t.name, t.enabled])),
  );
  const [showDescriptions, setShowDescriptions] = useState(false);
  const [reconnecting, setReconnecting] = useState(false);

  // Sync local state when server data changes (after save/refresh)
  useEffect(() => {
    setLocalTools(Object.fromEntries(server.tools.map((t) => [t.name, t.enabled])));
    setReconnecting(false); // Connection attempt finished (success or failure)
  }, [server.tools, server.connected, server.error]);

  const hasDescriptions = server.tools.some((t) => t.description);

  // Check if there are unsaved changes
  const isDirty = server.tools.some((t) => localTools[t.name] !== t.enabled);
  const enabledCount = Object.values(localTools).filter(Boolean).length;

  return (
    <div className={`mcp-server-card ${server.enabled ? "" : "disabled"}`}>
      <div className="mcp-server-header" onClick={onToggleExpand}>
        <i className={`codicon codicon-chevron-${expanded ? "down" : "right"} mcp-chevron`} />
        {reconnecting
          ? <i className="codicon codicon-loading codicon-modifier-spin mcp-spinner" />
          : <span className={`mcp-status-dot ${server.connected ? "connected" : server.error ? "error" : "disconnected"}`} />
        }
        <span className="mcp-server-name">{server.name}</span>
        <span className={`mcp-scope-badge ${server.scope}`} title={server.scope === "global" ? "Global (all projects)" : "Project-specific"}>
          {server.scope === "global" ? "G" : "P"}
        </span>
        <span className="mcp-tool-count">{enabledCount} tools</span>
        <div className="mcp-server-actions" onClick={(e) => e.stopPropagation()}>
          <label className="mcp-toggle" title={server.enabled ? "Disable server" : "Enable server"}>
            <input
              type="checkbox"
              checked={server.enabled}
              onChange={(e) => onToggleServer(server.name, e.target.checked)}
            />
            <span className="mcp-toggle-slider" />
          </label>
          <button
            className="mcp-icon-btn danger"
            onClick={() => onUninstall(server.name)}
            title="Remove server"
          >
            <i className="codicon codicon-trash" />
          </button>
        </div>
      </div>

      {expanded && (
        <div className="mcp-server-body">
          <div className="mcp-server-info">
            <span className="mcp-label">Transport:</span> {server.transport}
            {server.command && (
              <>
                <br />
                <span className="mcp-label">Command:</span>{" "}
                <code>{server.command} {server.args?.join(" ") ?? ""}</code>
              </>
            )}
          </div>

          {server.error && (
            <div className="mcp-server-error">
              <i className="codicon codicon-error" /> {server.error}
            </div>
          )}

          <div className="mcp-server-actions-row">
            {reconnecting && (
              <span className="mcp-connecting-text">
                <i className="codicon codicon-loading codicon-modifier-spin" /> Connecting...
              </span>
            )}
            {!server.connected && server.enabled && !reconnecting && (
              <button className="mcp-text-btn" onClick={() => { setReconnecting(true); onReconnect(server.name); }}>
                <i className="codicon codicon-refresh" /> Reconnect
              </button>
            )}
            {server.docsUrl && (
              <button className="mcp-text-btn" onClick={() => onOpenDocs(server.docsUrl!)}>
                <i className="codicon codicon-book" /> Docs
              </button>
            )}
          </div>

          {server.tools.length > 0 && (
            <div className="mcp-tools">
              <div className="mcp-tools-actions">
                <span className="mcp-tools-header">Tools</span>
                {hasDescriptions && (
                  <button
                    className="mcp-text-btn"
                    onClick={() => setShowDescriptions(!showDescriptions)}
                  >
                    {showDescriptions ? "Hide Details" : "Show Details"}
                  </button>
                )}
                <button
                  className="mcp-text-btn"
                  onClick={() => setLocalTools(Object.fromEntries(server.tools.map((t) => [t.name, true])))}
                >
                  Enable All
                </button>
                <button
                  className="mcp-text-btn"
                  onClick={() => setLocalTools(Object.fromEntries(server.tools.map((t) => [t.name, false])))}
                >
                  Disable All
                </button>
              </div>
              {server.tools.map((tool) => (
                <div key={tool.name} className="mcp-tool-item">
                  <label className="mcp-tool-row">
                    <input
                      type="checkbox"
                      checked={localTools[tool.name] ?? tool.enabled}
                      onChange={(e) => setLocalTools((prev) => ({ ...prev, [tool.name]: e.target.checked }))}
                    />
                    <span className="mcp-tool-name">{tool.name}</span>
                  </label>
                  {showDescriptions && tool.description && (
                    <div className="mcp-tool-desc">{tool.description}</div>
                  )}
                </div>
              ))}
              {isDirty && (
                <button
                  className="mcp-save-btn"
                  onClick={() => onSaveTools(server.name, localTools)}
                >
                  <i className="codicon codicon-save" /> Save Changes
                </button>
              )}
            </div>
          )}
        </div>
      )}
    </div>
  );
}

// ---------------------------------------------------------------------------
// Marketplace card
// ---------------------------------------------------------------------------

function MarketplaceCard({
  entry,
  installed,
  onInstall,
}: {
  entry: McpMarketplaceEntry;
  installed: boolean;
  onInstall: (scope: "project" | "global") => void;
}) {
  const [installing, setInstalling] = useState(false);

  // Clear installing state when installed status changes
  useEffect(() => {
    if (installed) setInstalling(false);
  }, [installed]);

  const handleInstall = (scope: "project" | "global") => {
    setInstalling(true);
    onInstall(scope);
  };

  return (
    <div className="mcp-marketplace-card">
      <div className="mcp-marketplace-header">
        <div className="mcp-marketplace-icon-placeholder">
          <i className="codicon codicon-extensions" />
        </div>
        <div className="mcp-marketplace-info">
          <div className="mcp-marketplace-name">
            {entry.name}
            {entry.verified && <i className="codicon codicon-verified-filled mcp-verified" title="Verified" />}
          </div>
          <div className="mcp-marketplace-author">{entry.author}</div>
        </div>
        {installed ? (
          <span className="mcp-install-btn installed">Installed</span>
        ) : installing ? (
          <span className="mcp-install-btn installing">
            <i className="codicon codicon-loading codicon-modifier-spin" /> Installing...
          </span>
        ) : (
          <div className="mcp-install-scope">
            <button
              className="mcp-install-btn"
              onClick={() => handleInstall("project")}
              title="Install for this project"
            >
              Project
            </button>
            <button
              className="mcp-install-btn mcp-install-global"
              onClick={() => handleInstall("global")}
              title="Install globally (all projects)"
            >
              Global
            </button>
          </div>
        )}
      </div>
      <div className="mcp-marketplace-desc">{entry.description}</div>
      {(entry.tags.length > 0 || entry.isRemote || entry.source === "npm") && (
        <div className="mcp-marketplace-tags">
          {entry.source === "npm" && <span className="mcp-tag mcp-tag-npm">npm</span>}
          {entry.isRemote && <span className="mcp-tag mcp-tag-remote">Remote</span>}
          {entry.tags.slice(0, 5).map((tag) => (
            <span key={tag} className="mcp-tag">
              {tag}
            </span>
          ))}
        </div>
      )}
      <div className="mcp-marketplace-stats">
        {entry.useCount > 0 && (
          <span className="mcp-stat">
            <i className="codicon codicon-arrow-down" /> {entry.useCount.toLocaleString()}
          </span>
        )}
        {entry.envVars.length > 0 && (
          <span className="mcp-stat" title={`Requires: ${entry.envVars.join(", ")}`}>
            <i className="codicon codicon-key" /> {entry.envVars.length} key{entry.envVars.length !== 1 ? "s" : ""}
          </span>
        )}
      </div>
    </div>
  );
}
