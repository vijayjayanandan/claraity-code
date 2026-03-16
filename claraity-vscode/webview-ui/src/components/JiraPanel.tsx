/**
 * Jira configuration panel.
 *
 * Full feature parity with inline HTML: profile selector with "New Profile",
 * form fields with token indicator, validation, connect/disconnect,
 * status badge, notifications, auto-refresh after operations.
 */
import { useState, useEffect, useCallback } from "react";
import type { WebViewMessage, JiraProfile } from "../types";

interface JiraPanelProps {
  postMessage: (msg: WebViewMessage) => void;
  onBack: () => void;
  profiles: JiraProfile[];
  connectedProfile: string | null;
  notification: { message: string; success: boolean } | null;
}

export function JiraPanel({
  postMessage,
  onBack,
  profiles,
  connectedProfile,
  notification,
}: JiraPanelProps) {
  const [selectedProfile, setSelectedProfile] = useState("");
  const [isNew, setIsNew] = useState(false);
  const [newProfileName, setNewProfileName] = useState("");
  const [jiraUrl, setJiraUrl] = useState("");
  const [username, setUsername] = useState("");
  const [apiToken, setApiToken] = useState("");
  const [hasToken, setHasToken] = useState(false);
  const [busy, setBusy] = useState(false);
  const [localError, setLocalError] = useState("");

  // Request profiles on mount
  useEffect(() => {
    postMessage({ type: "getJiraProfiles" });
  }, [postMessage]);

  // Auto-select connected or first profile when profiles arrive
  useEffect(() => {
    if (connectedProfile) {
      setSelectedProfile(connectedProfile);
    } else if (profiles.length === 1) {
      setSelectedProfile(profiles[0].name);
    }
  }, [profiles, connectedProfile]);

  // Populate fields when selection changes
  useEffect(() => {
    if (selectedProfile === "__new__") {
      setIsNew(true);
      setNewProfileName("");
      setJiraUrl("");
      setUsername("");
      setApiToken("");
      setHasToken(false);
    } else {
      setIsNew(false);
      const p = profiles.find((pr) => pr.name === selectedProfile);
      if (p) {
        setJiraUrl(p.jira_url || "");
        setUsername(p.username || "");
        setApiToken("");
        setHasToken(p.has_token);
      }
    }
    setLocalError("");
  }, [selectedProfile, profiles]);

  // Re-enable buttons when notification arrives
  useEffect(() => {
    if (notification) setBusy(false);
  }, [notification]);

  // Refresh profiles after successful save/connect/disconnect
  useEffect(() => {
    if (notification?.success) {
      postMessage({ type: "getJiraProfiles" });
    }
  }, [notification, postMessage]);

  const validate = useCallback((): boolean => {
    const profile = isNew ? newProfileName.trim() : selectedProfile;
    if (!profile) {
      setLocalError("Please select or enter a profile name.");
      return false;
    }
    if (isNew && !/^[a-zA-Z0-9_-]+$/.test(profile)) {
      setLocalError("Profile name: alphanumeric, hyphens, underscores only.");
      return false;
    }
    if (!jiraUrl.trim()) { setLocalError("Jira URL is required."); return false; }
    if (!username.trim()) { setLocalError("Username is required."); return false; }
    if (isNew && !apiToken.trim()) { setLocalError("API token is required for new profiles."); return false; }
    setLocalError("");
    return true;
  }, [isNew, newProfileName, selectedProfile, jiraUrl, username, apiToken]);

  const handleSave = useCallback(() => {
    if (!validate()) return;
    setBusy(true);
    postMessage({
      type: "saveJiraConfig",
      profile: isNew ? newProfileName.trim() : selectedProfile,
      jira_url: jiraUrl.trim(),
      username: username.trim(),
      api_token: apiToken.trim(),
    });
  }, [validate, isNew, newProfileName, selectedProfile, jiraUrl, username, apiToken, postMessage]);

  const handleConnect = useCallback(() => {
    const profile = isNew ? newProfileName.trim() : selectedProfile;
    if (!profile || profile === "__new__") {
      setLocalError("Please select a profile to connect.");
      return;
    }
    setBusy(true);
    postMessage({ type: "connectJira", profile });
  }, [isNew, newProfileName, selectedProfile, postMessage]);

  const handleDisconnect = useCallback(() => {
    setBusy(true);
    postMessage({ type: "disconnectJira" });
  }, [postMessage]);

  const effectiveProfile = isNew ? newProfileName.trim() : selectedProfile;
  const isConnected = connectedProfile && connectedProfile === effectiveProfile;
  const errorMsg = localError || (notification && !notification.success ? notification.message : "");
  const successMsg = notification?.success ? notification.message : "";

  return (
    <div className="session-panel">
      <div className="session-panel-header">
        <button className="btn-secondary" onClick={onBack}>
          <i className="codicon codicon-arrow-left" /> Back
        </button>
        <span className="settings-header-title">Jira Settings</span>
        <span className={`connection-badge ${connectedProfile ? "connected" : "disconnected"}`}>
          {connectedProfile || "disconnected"}
        </span>
      </div>

      <div className="settings-body">
        {/* Notifications */}
        {errorMsg && (
          <div className="notification-banner error">{errorMsg}</div>
        )}
        {successMsg && (
          <div className="notification-banner success">{successMsg}</div>
        )}

        {/* Profile selector */}
        <div className="form-field">
          <label className="form-label">Profile</label>
          <select
            className="form-input"
            value={isNew ? "__new__" : selectedProfile}
            onChange={(e) => setSelectedProfile(e.target.value)}
          >
            <option value="">-- Select profile --</option>
            <option value="__new__">+ New Profile</option>
            {profiles.map((p) => (
              <option key={p.name} value={p.name}>
                {p.name}{connectedProfile === p.name ? " (connected)" : ""}
              </option>
            ))}
          </select>
        </div>

        {/* New profile name */}
        {isNew && (
          <div className="form-field">
            <label className="form-label">Profile Name</label>
            <input
              className="form-input"
              type="text"
              value={newProfileName}
              onChange={(e) => setNewProfileName(e.target.value)}
              placeholder="my-profile"
            />
          </div>
        )}

        {/* Jira URL */}
        <div className="form-field">
          <label className="form-label">Jira URL</label>
          <input
            className="form-input"
            type="text"
            value={jiraUrl}
            onChange={(e) => setJiraUrl(e.target.value)}
            placeholder="https://your-org.atlassian.net"
          />
        </div>

        {/* Username */}
        <div className="form-field">
          <label className="form-label">Username (email)</label>
          <input
            className="form-input"
            type="text"
            value={username}
            onChange={(e) => setUsername(e.target.value)}
          />
        </div>

        {/* API Token */}
        <div className="form-field">
          <label className="form-label">
            API Token{" "}
            <span className="form-label-hint">
              {hasToken ? "(token stored)" : "(not set)"}
            </span>
          </label>
          <input
            className="form-input"
            type="password"
            value={apiToken}
            onChange={(e) => setApiToken(e.target.value)}
          />
        </div>

        {/* Actions */}
        <div className="form-actions">
          <button className="btn-primary" onClick={handleSave} disabled={busy}>
            Save
          </button>
          {isConnected ? (
            <button className="btn-danger" onClick={handleDisconnect} disabled={busy}>
              Disconnect
            </button>
          ) : (
            <button className="btn-primary" onClick={handleConnect} disabled={busy || !effectiveProfile}>
              Connect
            </button>
          )}
          <button className="btn-secondary" onClick={onBack}>
            Cancel
          </button>
        </div>
      </div>
    </div>
  );
}
