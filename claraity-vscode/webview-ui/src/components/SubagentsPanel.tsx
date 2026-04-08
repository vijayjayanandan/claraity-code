/**
 * Subagents management panel.
 *
 * - Lists all subagents (built-in + project-level custom)
 * - Built-ins are read-only but forkable
 * - Project-level subagents are editable and deletable
 * - Inline editor form for create/edit
 */
import { useState, useEffect, useCallback } from "react";
import type { WebViewMessage, SubAgentInfo } from "../types";

interface SubagentsPanelProps {
  postMessage: (msg: WebViewMessage) => void;
  onBack: () => void;
  subagents: SubAgentInfo[];
  availableTools: string[];
  notification: { message: string; success: boolean } | null;
  onClearNotification: () => void;
}

type View = "list" | "edit";

interface FormState {
  name: string;
  description: string;
  systemPrompt: string;
  selectedTools: string[];  // empty = all tools (null in config)
  isNew: boolean;
  isFork: boolean;
  originalName: string;
}

const EMPTY_FORM: FormState = {
  name: "",
  description: "",
  systemPrompt: "",
  selectedTools: [],
  isNew: true,
  isFork: false,
  originalName: "",
};

export function SubagentsPanel({
  postMessage,
  onBack,
  subagents,
  availableTools,
  notification,
  onClearNotification,
}: SubagentsPanelProps) {
  const [view, setView] = useState<View>("list");
  const [form, setForm] = useState<FormState>(EMPTY_FORM);
  const [localError, setLocalError] = useState("");
  const [confirmDelete, setConfirmDelete] = useState<string | null>(null);

  // Fetch list on mount
  useEffect(() => {
    postMessage({ type: "listSubagents" });
  }, [postMessage]);

  // After successful save/delete: refresh list, return to list view, clear notification
  useEffect(() => {
    if (notification?.success) {
      postMessage({ type: "listSubagents" });
      setView("list");
      // Clear after a short delay so the success message is briefly visible
      const t = setTimeout(() => onClearNotification(), 3000);
      return () => clearTimeout(t);
    }
  }, [notification, postMessage, onClearNotification]);

  const handleNew = useCallback(() => {
    onClearNotification();
    setForm(EMPTY_FORM);
    setLocalError("");
    setView("edit");
  }, [onClearNotification]);

  const handleEdit = useCallback((agent: SubAgentInfo) => {
    onClearNotification();
    setForm({
      name: agent.name,
      description: agent.description,
      systemPrompt: agent.system_prompt,
      selectedTools: agent.tools ?? [],
      isNew: false,
      isFork: false,
      originalName: agent.name,
    });
    setLocalError("");
    setView("edit");
  }, [onClearNotification]);

  const handleFork = useCallback((agent: SubAgentInfo) => {
    onClearNotification();
    setForm({
      name: agent.name + "-custom",
      description: agent.description,
      systemPrompt: agent.system_prompt,
      selectedTools: agent.tools ?? [],
      isNew: true,
      isFork: true,
      originalName: agent.name,
    });
    setLocalError("");
    setView("edit");
  }, [onClearNotification]);

  const handleSave = useCallback(() => {
    const name = form.name.trim();
    const description = form.description.trim();
    const systemPrompt = form.systemPrompt.trim();

    if (!name) { setLocalError("Name is required."); return; }
    if (!/^[a-z][a-z0-9-]*$/.test(name)) {
      setLocalError("Name must be lowercase letters, digits, and hyphens (e.g. my-agent).");
      return;
    }
    if (!description) { setLocalError("Description is required."); return; }
    if (!systemPrompt) { setLocalError("System prompt is required."); return; }

    // Empty selection = null (inherit all tools), otherwise send the list
    const toolsList = form.selectedTools.length > 0 ? form.selectedTools : null;

    setLocalError("");
    postMessage({
      type: "saveSubagent",
      name,
      description,
      systemPrompt,
      tools: toolsList,
      isFork: form.isFork,
    });
  }, [form, postMessage]);

  const handleDelete = useCallback((name: string) => {
    postMessage({ type: "deleteSubagent", name });
    setConfirmDelete(null);
  }, [postMessage]);

  const handleOpenFile = useCallback((name: string) => {
    postMessage({ type: "openSubagentFile", name });
  }, [postMessage]);

  const handleBack = useCallback(() => {
    if (view === "edit") {
      setView("list");
    } else {
      onBack();
    }
  }, [view, onBack]);

  // ── Edit form ──────────────────────────────────────────────────────────────
  if (view === "edit") {
    const title = form.isNew
      ? form.isFork ? `Fork: ${form.originalName}` : "New Subagent"
      : `Edit: ${form.name}`;

    return (
      <div className="panel">
        <div className="panel-header">
          <button className="back-btn" onClick={handleBack} aria-label="Back">
            <i className="codicon codicon-arrow-left" />
          </button>
          <span className="panel-title">{title}</span>
        </div>

        <div className="panel-content">
          {localError && (
            <div className="notification error">{localError}</div>
          )}

          <div className="form-group">
            <label className="form-label">Name</label>
            <input
              className="form-input"
              type="text"
              value={form.name}
              placeholder="my-agent"
              disabled={!form.isNew}
              onChange={(e) => setForm((f) => ({ ...f, name: e.target.value }))}
            />
            {!form.isNew && (
              <span className="form-hint">Name cannot be changed after creation.</span>
            )}
          </div>

          <div className="form-group">
            <label className="form-label">Description</label>
            <input
              className="form-input"
              type="text"
              value={form.description}
              placeholder="Short description shown to the agent"
              onChange={(e) => setForm((f) => ({ ...f, description: e.target.value }))}
            />
          </div>

          <div className="form-group">
            <label className="form-label">System Prompt</label>
            <textarea
              className="form-textarea"
              value={form.systemPrompt}
              rows={10}
              placeholder="You are a specialized agent that..."
              onChange={(e) => setForm((f) => ({ ...f, systemPrompt: e.target.value }))}
            />
          </div>

          <div className="form-group">
            <label className="form-label">Allowed Tools</label>
            <span className="form-hint">Uncheck tools to restrict access. Leave all unchecked to grant access to all tools.</span>
            <div className="tools-checklist">
              {availableTools.map((tool) => (
                <label key={tool} className="tool-checkbox-row">
                  <input
                    type="checkbox"
                    checked={form.selectedTools.length === 0 || form.selectedTools.includes(tool)}
                    onChange={(e) => {
                      setForm((f) => {
                        // If currently "all selected" (empty array), expand to full list first
                        const current = f.selectedTools.length === 0
                          ? availableTools
                          : f.selectedTools;
                        const next = e.target.checked
                          ? [...current, tool]
                          : current.filter((t) => t !== tool);
                        // If all tools selected, collapse back to empty (meaning "all")
                        return { ...f, selectedTools: next.length === availableTools.length ? [] : next };
                      });
                    }}
                  />
                  <span className="tool-name">{tool}</span>
                </label>
              ))}
            </div>
            {form.selectedTools.length > 0 && form.selectedTools.length < availableTools.length && (
              <span className="form-hint">{form.selectedTools.length} of {availableTools.length} tools selected.</span>
            )}
            {form.selectedTools.length === 0 && (
              <span className="form-hint">All tools allowed (default).</span>
            )}
          </div>

          <div className="form-actions">
            <button className="btn-primary" onClick={handleSave}>Save</button>
            <button className="btn-secondary" onClick={handleBack}>Cancel</button>
          </div>
        </div>
      </div>
    );
  }

  // ── List view ──────────────────────────────────────────────────────────────
  const builtins = subagents.filter((a) => a.source === "builtin");
  const custom = subagents.filter((a) => a.source !== "builtin");

  return (
    <div className="panel">
      <div className="panel-header">
        <button className="back-btn" onClick={handleBack} aria-label="Back">
          <i className="codicon codicon-arrow-left" />
        </button>
        <span className="panel-title">Subagents</span>
        <button
          className="toolbar-icon toolbar-icon--with-label"
          onClick={handleNew}
          title="New Subagent"
          aria-label="New Subagent"
        >
          <i className="codicon codicon-add" />
          <span>New Subagent</span>
        </button>
      </div>

      {notification && (
        <div className={`notification ${notification.success ? "success" : "error"}`}>
          {notification.message}
        </div>
      )}

      <div className="panel-content">
        {/* Custom subagents */}
        {custom.length > 0 && (
          <section className="subagents-section">
            <h3 className="section-heading">Project Subagents</h3>
            {custom.map((agent) => (
              <SubagentRow
                key={agent.name}
                agent={agent}
                onEdit={handleEdit}
                onDelete={(name) => setConfirmDelete(name)}
                onOpenFile={handleOpenFile}
              />
            ))}
          </section>
        )}

        {/* Built-in subagents */}
        <section className="subagents-section">
          <h3 className="section-heading">Built-in Subagents</h3>
          {builtins.length === 0 && (
            <p className="empty-text">No built-in subagents found.</p>
          )}
          {builtins.map((agent) => (
            <SubagentRow
              key={agent.name}
              agent={agent}
              onFork={handleFork}
            />
          ))}
        </section>

        {custom.length === 0 && builtins.length === 0 && (
          <p className="empty-text">No subagents found. Click + to create one.</p>
        )}
      </div>

      {/* Delete confirmation */}
      {confirmDelete && (
        <div className="modal-overlay">
          <div className="modal">
            <p>Delete subagent <strong>{confirmDelete}</strong>?</p>
            <div className="form-actions">
              <button className="btn-danger" onClick={() => handleDelete(confirmDelete)}>Delete</button>
              <button className="btn-secondary" onClick={() => setConfirmDelete(null)}>Cancel</button>
            </div>
          </div>
        </div>
      )}
    </div>
  );
}

// ── SubagentRow ──────────────────────────────────────────────────────────────

interface SubagentRowProps {
  agent: SubAgentInfo;
  onEdit?: (agent: SubAgentInfo) => void;
  onFork?: (agent: SubAgentInfo) => void;
  onDelete?: (name: string) => void;
  onOpenFile?: (name: string) => void;
}

function SubagentRow({ agent, onEdit, onFork, onDelete, onOpenFile }: SubagentRowProps) {
  const isBuiltin = agent.source === "builtin";

  return (
    <div className="subagent-row">
      <div className="subagent-info">
        <span className="subagent-name">{agent.name}</span>
        <span className="subagent-desc">{agent.description}</span>
        {agent.tools && agent.tools.length > 0 && (
          <span className="subagent-tools">{agent.tools.length} tools</span>
        )}
      </div>
      <div className="subagent-actions">
        {isBuiltin ? (
          // Built-ins: fork only
          <button
            className="toolbar-icon"
            onClick={() => onFork?.(agent)}
            title="Fork to project"
            aria-label="Fork"
          >
            <i className="codicon codicon-repo-forked" />
          </button>
        ) : (
          // Custom: edit, open file, delete
          <>
            <button
              className="toolbar-icon"
              onClick={() => onEdit?.(agent)}
              title="Edit"
              aria-label="Edit"
            >
              <i className="codicon codicon-edit" />
            </button>
            {agent.config_path && (
              <button
                className="toolbar-icon"
                onClick={() => onOpenFile?.(agent.name)}
                title="Open file"
                aria-label="Open file"
              >
                <i className="codicon codicon-go-to-file" />
              </button>
            )}
            <button
              className="toolbar-icon"
              onClick={() => onDelete?.(agent.name)}
              title="Delete"
              aria-label="Delete"
            >
              <i className="codicon codicon-trash" />
            </button>
          </>
        )}
      </div>
    </div>
  );
}
