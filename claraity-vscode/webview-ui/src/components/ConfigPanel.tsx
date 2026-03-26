/**
 * LLM configuration settings panel.
 *
 * Full feature parity with inline HTML: backend selector, base URL,
 * API key with stored indicator, model with fetch/list/typeahead,
 * temperature, max tokens, context window, thinking budget,
 * web search config, subagent models with typeahead,
 * save/cancel in header — enabled only when form is dirty.
 */
import { useState, useEffect, useCallback, useMemo, useRef } from "react";
import type { WebViewMessage } from "../types";

interface ConfigPanelProps {
  postMessage: (msg: WebViewMessage) => void;
  onBack: () => void;
  configData: Record<string, unknown> | null;
  configSubagentNames: string[];
  configModels: { models: string[]; error?: string } | null;
  configNotification: { message: string; success: boolean } | null;
}

/**
 * Canonical snapshot of all persisted config values.
 * Used for dirty-checking, cancel-reset, and save correlation.
 * hasApiKey / hasSearchKey are display-only flags (not editable values)
 * but are included so Cancel can restore the hint labels accurately.
 */
interface ConfigSnapshot {
  backend: string;
  baseUrl: string;
  apiKey: string;
  hasApiKey: boolean;
  model: string;
  temperature: number;
  maxTokens: number;
  contextWindow: number;
  thinkingBudget: string;
  searchKey: string;
  hasSearchKey: boolean;
  subagentModels: Record<string, string>;
}

function snapshotEqual(a: ConfigSnapshot, b: ConfigSnapshot): boolean {
  if (
    a.backend !== b.backend ||
    a.baseUrl !== b.baseUrl ||
    a.apiKey !== b.apiKey ||
    a.model !== b.model ||
    a.temperature !== b.temperature ||
    a.maxTokens !== b.maxTokens ||
    a.contextWindow !== b.contextWindow ||
    a.thinkingBudget !== b.thinkingBudget ||
    a.searchKey !== b.searchKey
  ) return false;
  const aKeys = Object.keys(a.subagentModels).sort();
  const bKeys = Object.keys(b.subagentModels).sort();
  if (aKeys.join(",") !== bKeys.join(",")) return false;
  return aKeys.every((k) => a.subagentModels[k] === b.subagentModels[k]);
}

/** Parse raw server config into a typed ConfigSnapshot. */
function parseSnapshot(cfg: Record<string, unknown>): ConfigSnapshot {
  return {
    backend: typeof cfg.backend_type === "string" ? cfg.backend_type : "openai",
    baseUrl: typeof cfg.base_url === "string" ? cfg.base_url : "",
    apiKey: typeof cfg.api_key === "string" ? cfg.api_key : "",
    hasApiKey: !!cfg.has_api_key,
    model: typeof cfg.model === "string" ? cfg.model : "",
    temperature: cfg.temperature != null ? Number(cfg.temperature) : 0.2,
    maxTokens: cfg.max_tokens != null ? Number(cfg.max_tokens) : 16384,
    contextWindow: cfg.context_window != null ? Number(cfg.context_window) : 131072,
    thinkingBudget: cfg.thinking_budget != null ? String(cfg.thinking_budget) : "",
    searchKey: typeof cfg.search_key === "string" ? cfg.search_key : "",
    hasSearchKey: !!cfg.has_search_key,
    subagentModels: (cfg.subagent_models != null && typeof cfg.subagent_models === "object")
      ? { ...(cfg.subagent_models as Record<string, string>) }
      : {},
  };
}

/** Derive whether "use same model" checkbox should be checked from a snapshot. */
function deriveSameModel(snap: ConfigSnapshot, subagentNames: string[]): boolean {
  if (subagentNames.length === 0 || !snap.model) return false;
  return subagentNames.every((n) => (snap.subagentModels[n] ?? "") === snap.model);
}

export function ConfigPanel({
  postMessage,
  onBack,
  configData,
  configSubagentNames,
  configModels,
  configNotification,
}: ConfigPanelProps) {
  // ── Form state ──────────────────────────────────────────────────────────────
  const [backend, setBackend] = useState("openai");
  const [baseUrl, setBaseUrl] = useState("");
  const [apiKey, setApiKey] = useState("");
  const [hasApiKey, setHasApiKey] = useState(false);
  const [model, setModel] = useState("");
  const [temperature, setTemperature] = useState(0.2);
  const [maxTokens, setMaxTokens] = useState(16384);
  const [contextWindow, setContextWindow] = useState(131072);
  const [thinkingBudget, setThinkingBudget] = useState("");
  const [searchKey, setSearchKey] = useState("");
  const [hasSearchKey, setHasSearchKey] = useState(false);
  const [subagentModels, setSubagentModels] = useState<Record<string, string>>({});
  const [showSubagents, setShowSubagents] = useState(true);
  const [sameModel, setSameModel] = useState(false);
  const [fetchStatus, setFetchStatus] = useState("");

  // ── Save / notification state ────────────────────────────────────────────────
  const [isSaving, setIsSaving] = useState(false);
  const [notificationDismissed, setNotificationDismissed] = useState(false);

  // Ref mirror of isSaving so the configNotification effect always reads the
  // current value without needing isSaving in its dependency array (which would
  // cause it to re-run and reset the dismiss timer on unrelated renders).
  const isSavingRef = useRef(false);
  useEffect(() => { isSavingRef.current = isSaving; }, [isSaving]);

  // Last snapshot committed to disk — basis for dirty-checking and cancel reset.
  const savedSnapshot = useRef<ConfigSnapshot | null>(null);
  // Snapshot captured at the moment Save is clicked — committed only on success.
  const pendingSnapshot = useRef<ConfigSnapshot | null>(null);

  // ── Typeahead state ──────────────────────────────────────────────────────────
  const [modelListOpen, setModelListOpen] = useState(false);
  const [activeSubagentDropdown, setActiveSubagentDropdown] = useState<string | null>(null);
  const hideTimerRef = useRef<ReturnType<typeof setTimeout> | null>(null);

  // ── Hydrate form from server ─────────────────────────────────────────────────
  // Request config on mount.
  useEffect(() => {
    postMessage({ type: "getConfig" });
  }, [postMessage]);

  // Apply incoming configData only when safe: not dirty and not mid-save.
  // This prevents a background CONFIG_LOADED from overwriting in-progress edits
  // or an in-flight save from being displaced before its ACK arrives.
  const isDirtyRef = useRef(false);
  useEffect(() => {
    if (!configData) return;
    if (isSavingRef.current || isDirtyRef.current) return;
    const snap = parseSnapshot(configData);
    savedSnapshot.current = snap;
    applySnapshot(snap);
  }, [configData]); // isSaving / isDirty intentionally read via refs, not deps

  /** Apply a snapshot to all form fields (shared by hydration and cancel). */
  function applySnapshot(snap: ConfigSnapshot) {
    setBackend(snap.backend);
    setBaseUrl(snap.baseUrl);
    setApiKey(snap.apiKey);
    setHasApiKey(snap.hasApiKey);
    setModel(snap.model);
    setTemperature(snap.temperature);
    setMaxTokens(snap.maxTokens);
    setContextWindow(snap.contextWindow);
    setThinkingBudget(snap.thinkingBudget);
    setSearchKey(snap.searchKey);
    setHasSearchKey(snap.hasSearchKey);
    setSubagentModels({ ...snap.subagentModels });
    setSameModel(deriveSameModel(snap, configSubagentNames));
    setFetchStatus("");
  }

  // ── Round-trip completion ────────────────────────────────────────────────────
  // configNotification is the sole signal that the save completed.
  // isSavingRef avoids a stale closure without adding isSaving to the dep array
  // (which would incorrectly re-run the dismiss timer whenever saving changes).
  useEffect(() => {
    if (!configNotification) return;
    setNotificationDismissed(false);

    if (isSavingRef.current) {
      setIsSaving(false);
      if (configNotification.success && pendingSnapshot.current) {
        // Commit only on confirmed success; on error the form stays dirty so
        // the user can see what failed and retry.
        savedSnapshot.current = pendingSnapshot.current;
      }
      pendingSnapshot.current = null;
    }

    const timer = setTimeout(() => setNotificationDismissed(true), 4000);
    return () => clearTimeout(timer);
  }, [configNotification]);

  // ── Dirty tracking ───────────────────────────────────────────────────────────
  const currentSnapshot = useMemo<ConfigSnapshot>(() => ({
    backend,
    baseUrl,
    apiKey,
    hasApiKey,
    model,
    temperature,
    maxTokens,
    contextWindow,
    thinkingBudget,
    searchKey,
    hasSearchKey,
    subagentModels,
  }), [backend, baseUrl, apiKey, hasApiKey, model, temperature, maxTokens, contextWindow, thinkingBudget, searchKey, hasSearchKey, subagentModels]);

  const isDirty = useMemo(() => {
    if (!savedSnapshot.current) return false;
    return !snapshotEqual(currentSnapshot, savedSnapshot.current);
  }, [currentSnapshot]);

  // Keep ref in sync so the configData hydration effect can read it safely.
  useEffect(() => { isDirtyRef.current = isDirty; }, [isDirty]);

  // ── Backend change ───────────────────────────────────────────────────────────
  const handleBackendChange = useCallback((val: string) => {
    setBackend(val);
    if (val === "ollama") setBaseUrl("http://localhost:11434");
    else if (val === "anthropic") setBaseUrl("");
  }, []);

  // ── Fetch models ─────────────────────────────────────────────────────────────
  const handleFetchModels = useCallback(() => {
    setFetchStatus("Fetching...");
    postMessage({
      type: "listModels",
      backend,
      base_url: baseUrl,
      api_key: apiKey || "__use_stored__",
    });
  }, [backend, baseUrl, apiKey, postMessage]);

  useEffect(() => {
    if (!configModels) return;
    if (configModels.error) {
      setFetchStatus("Error: " + configModels.error);
    } else if (configModels.models.length === 0) {
      setFetchStatus("No models found");
    } else {
      setFetchStatus(configModels.models.length + " model(s)");
    }
  }, [configModels]);

  // ── Model typeahead ──────────────────────────────────────────────────────────
  const filteredModels = useMemo(() => {
    const all = configModels?.models ?? [];
    if (all.length === 0) return [];
    const query = model.toLowerCase().trim();
    return query ? all.filter((m) => m.toLowerCase().includes(query)) : all;
  }, [configModels, model]);

  const scheduleHideModelList = useCallback(() => {
    hideTimerRef.current = setTimeout(() => setModelListOpen(false), 200);
  }, []);
  const cancelHideModelList = useCallback(() => {
    if (hideTimerRef.current) clearTimeout(hideTimerRef.current);
  }, []);

  const handleModelFocus = useCallback(() => {
    if ((configModels?.models.length ?? 0) > 0) setModelListOpen(true);
  }, [configModels]);

  const handleModelClear = useCallback(() => {
    setModel("");
    if ((configModels?.models.length ?? 0) > 0) setModelListOpen(true);
  }, [configModels]);

  // ── Same-model sync ──────────────────────────────────────────────────────────
  // When the checkbox is on, keep all subagent fields in sync with the main model.
  // subagentModels is intentionally excluded from deps to avoid a feedback loop.
  useEffect(() => {
    if (!sameModel) return;
    setSubagentModels(
      Object.fromEntries(configSubagentNames.map((n) => [n, model]))
    );
  }, [sameModel, model, configSubagentNames]);

  // ── Subagent typeahead ───────────────────────────────────────────────────────
  const filteredSubagentModels = useCallback((name: string) => {
    const all = configModels?.models ?? [];
    if (all.length === 0) return [];
    const query = (subagentModels[name] || "").toLowerCase().trim();
    return query ? all.filter((m) => m.toLowerCase().includes(query)) : all;
  }, [configModels, subagentModels]);

  // ── Save ─────────────────────────────────────────────────────────────────────
  const handleSave = useCallback(() => {
    // Build the canonical payload — only non-empty subagent overrides are sent.
    // pendingSnapshot stores the same filtered shape so dirty-check stays accurate
    // after a successful save.
    const saModels: Record<string, string> = {};
    for (const name of configSubagentNames) {
      const val = subagentModels[name]?.trim();
      if (val) saModels[name] = val;
    }

    const snap: ConfigSnapshot = {
      ...currentSnapshot,
      subagentModels: saModels, // normalized: empty entries stripped
    };
    pendingSnapshot.current = snap;
    setIsSaving(true);

    postMessage({
      type: "saveConfig",
      config: {
        backend_type: snap.backend,
        base_url: snap.baseUrl,
        api_key: snap.apiKey,
        model: snap.model,
        temperature: snap.temperature,
        max_tokens: snap.maxTokens,
        context_window: snap.contextWindow,
        thinking_budget: snap.thinkingBudget || null,
        subagent_models: snap.subagentModels,
        search_key: snap.searchKey,
      },
    });
  }, [currentSnapshot, subagentModels, configSubagentNames, postMessage]);

  // ── Cancel ───────────────────────────────────────────────────────────────────
  // Resets all fields to the last saved values. Does not navigate away.
  const handleCancel = useCallback(() => {
    const snap = savedSnapshot.current;
    if (!snap) { onBack(); return; }
    applySnapshot(snap);
  // applySnapshot is defined in render scope and stable; configSubagentNames
  // is captured via applySnapshot -> deriveSameModel
  // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [onBack, configSubagentNames]);

  const hasModels = (configModels?.models.length ?? 0) > 0;

  return (
    <div className="session-panel">
      <div className="session-panel-header">
        <button className="btn-secondary" onClick={onBack}>
          <i className="codicon codicon-arrow-left" /> Back
        </button>
        <span className="settings-header-title">Settings</span>
        <div className="settings-header-actions">
          <button
            className="btn-secondary settings-header-btn"
            onClick={handleCancel}
            disabled={!isDirty || isSaving}
            title="Discard changes"
          >
            Cancel
          </button>
          <button
            className="btn-primary settings-header-btn"
            onClick={handleSave}
            disabled={!isDirty || isSaving}
            title="Save settings"
          >
            {isSaving ? <span className="save-spinner" /> : "Save"}
          </button>
        </div>
      </div>

      <div className="settings-body">
        {/* Notification banner */}
        {configNotification && !notificationDismissed && (
          <div className={`notification-banner ${configNotification.success ? "success" : "error"}`}>
            {configNotification.message}
          </div>
        )}

        {/*
          Wrap all form controls in a fieldset so the browser natively disables
          every input/select/button inside while a save is in flight. This keeps
          the submitted values consistent with pendingSnapshot.
        */}
        <fieldset disabled={isSaving} className="settings-fieldset">

          {/* Backend */}
          <Field label="Backend">
            <select className="form-input" value={backend} onChange={(e) => handleBackendChange(e.target.value)}>
              <option value="openai">OpenAI-compatible</option>
              <option value="ollama">Ollama</option>
              <option value="anthropic">Anthropic</option>
            </select>
          </Field>

          {/* Base URL: not shown for Anthropic (hardcoded by SDK) */}
          {backend !== "anthropic" && (
            <Field label="Base URL">
              <input
                className="form-input"
                type="text"
                value={baseUrl}
                onChange={(e) => setBaseUrl(e.target.value)}
                placeholder="https://api.openai.com/v1"
              />
            </Field>
          )}

          {/* API Key */}
          <Field label={<>API Key <span className="form-label-hint">{hasApiKey ? "(key stored)" : "(not set)"}</span></>}>
            <input
              className="form-input"
              type="password"
              value={apiKey}
              onChange={(e) => setApiKey(e.target.value)}
              placeholder="sk-..."
            />
          </Field>

          {/* Model with typeahead */}
          <Field label="Model">
            <div className="form-row" style={{ marginBottom: 4 }}>
              <div className="model-input-wrap">
                <input
                  className="form-input"
                  type="text"
                  value={model}
                  onChange={(e) => { setModel(e.target.value); if (hasModels) setModelListOpen(true); }}
                  onFocus={handleModelFocus}
                  onBlur={scheduleHideModelList}
                  placeholder="gpt-4o"
                />
                {model && (
                  <button
                    className="model-clear-btn"
                    onMouseDown={(e) => { e.preventDefault(); handleModelClear(); }}
                    tabIndex={-1}
                    title="Clear"
                  >
                    <i className="codicon codicon-close" />
                  </button>
                )}
              </div>
              <button className="btn-secondary" onClick={handleFetchModels} style={{ whiteSpace: "nowrap" }}>
                Fetch
              </button>
            </div>
            {fetchStatus && <div className="form-label-hint" style={{ marginBottom: 4 }}>{fetchStatus}</div>}
            {modelListOpen && filteredModels.length > 0 && (
              <div className="model-list" onMouseDown={(e) => e.preventDefault()}>
                {filteredModels.map((m) => (
                  <div
                    key={m}
                    className={`model-list-item${m === model ? " selected" : ""}`}
                    onClick={() => { setModel(m); setModelListOpen(false); cancelHideModelList(); }}
                    style={m === model ? {
                      background: "var(--vscode-list-activeSelectionBackground)",
                      color: "var(--vscode-list-activeSelectionForeground)",
                    } : undefined}
                  >
                    {m}
                  </div>
                ))}
              </div>
            )}
          </Field>

          {/* Temperature */}
          <Field label={`Temperature: ${temperature}`}>
            <input
              type="range"
              min={0}
              max={2}
              step={0.1}
              value={temperature}
              onChange={(e) => setTemperature(parseFloat(e.target.value))}
              style={{ width: "100%" }}
            />
            <div className="slider-range-labels">
              <span>0</span>
              <span>1</span>
              <span>2</span>
            </div>
          </Field>

          {/* Max Tokens */}
          <Field label="Max Tokens">
            <input
              className="form-input"
              type="number"
              value={maxTokens}
              onChange={(e) => setMaxTokens(parseInt(e.target.value) || 0)}
            />
          </Field>

          {/* Context Window */}
          <Field label="Context Window">
            <input
              className="form-input"
              type="number"
              value={contextWindow}
              onChange={(e) => setContextWindow(parseInt(e.target.value) || 0)}
            />
          </Field>

          {/* Thinking Budget: only relevant for Anthropic (Claude extended thinking) */}
          {backend === "anthropic" && (
            <Field label="Thinking Budget (tokens)">
              <input
                className="form-input"
                type="text"
                value={thinkingBudget}
                onChange={(e) => setThinkingBudget(e.target.value)}
                placeholder="(leave empty for default)"
              />
            </Field>
          )}

          {/* Web Search */}
          <div className="settings-section">
            <div className="settings-section-label">Web Search</div>
            <Field label={<>Search API Key <span className="form-label-hint">{hasSearchKey ? "(key stored)" : "(not set)"}</span></>}>
              <input
                className="form-input"
                type="password"
                value={searchKey}
                onChange={(e) => setSearchKey(e.target.value)}
                placeholder="tvly-..."
              />
            </Field>
          </div>

          {/* Subagent Models: expanded by default */}
          {configSubagentNames.length > 0 && (
            <div className="settings-section">
              <button
                className="disclosure-row"
                onClick={() => setShowSubagents(!showSubagents)}
              >
                <i className={`codicon codicon-chevron-${showSubagents ? "down" : "right"}`} />
                <span className="settings-section-label" style={{ margin: 0 }}>Subagent Models</span>
              </button>
              {showSubagents && (
                <div style={{ paddingLeft: 8, paddingTop: 4 }}>
                  <div style={{ marginBottom: 8 }}>
                    <label className="form-label" style={{ display: "flex", alignItems: "center", gap: 6, marginBottom: 0, cursor: "pointer" }}>
                      <input
                        type="checkbox"
                        checked={sameModel}
                        onChange={(e) => setSameModel(e.target.checked)}
                      />
                      Use main model for all subagents
                    </label>
                  </div>
                  {configSubagentNames.map((name) => (
                    <div key={name} style={{ marginBottom: 6, position: "relative" }}>
                      <label className="form-label">{name}</label>
                      <div className="model-input-wrap">
                        <input
                          className="form-input"
                          type="text"
                          value={subagentModels[name] || ""}
                          onChange={(e) => {
                            const val = e.target.value;
                            setSubagentModels((prev) => ({ ...prev, [name]: val }));
                          }}
                          onFocus={() => { if (hasModels) setActiveSubagentDropdown(name); }}
                          onBlur={() => setTimeout(() => setActiveSubagentDropdown((cur) => cur === name ? null : cur), 200)}
                          placeholder="(inherit from main)"
                          disabled={sameModel}
                        />
                        {!sameModel && subagentModels[name] && (
                          <button
                            className="model-clear-btn"
                            onMouseDown={(e) => {
                              e.preventDefault();
                              setSubagentModels((prev) => ({ ...prev, [name]: "" }));
                            }}
                            tabIndex={-1}
                            title="Clear"
                          >
                            <i className="codicon codicon-close" />
                          </button>
                        )}
                      </div>
                      {activeSubagentDropdown === name && filteredSubagentModels(name).length > 0 && (
                        <div
                          className="model-list sa-typeahead"
                          onMouseDown={(e) => e.preventDefault()}
                        >
                          {filteredSubagentModels(name).map((m) => (
                            <div
                              key={m}
                              className={`model-list-item${subagentModels[name] === m ? " selected" : ""}`}
                              onClick={() => {
                                setSubagentModels((prev) => ({ ...prev, [name]: m }));
                                setActiveSubagentDropdown(null);
                              }}
                              style={subagentModels[name] === m ? {
                                background: "var(--vscode-list-activeSelectionBackground)",
                                color: "var(--vscode-list-activeSelectionForeground)",
                              } : undefined}
                            >
                              {m}
                            </div>
                          ))}
                        </div>
                      )}
                    </div>
                  ))}
                </div>
              )}
            </div>
          )}

        </fieldset>
      </div>
    </div>
  );
}

function Field({ label, children }: { label: React.ReactNode; children: React.ReactNode }) {
  return (
    <div className="form-field">
      <label className="form-label">{label}</label>
      {children}
    </div>
  );
}
