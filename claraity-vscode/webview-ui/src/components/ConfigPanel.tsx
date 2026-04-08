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

/** Sentinel value used to display dots in a password field without storing the real key. */
const KEY_STORED_SENTINEL = "__stored__";

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
  hasApiKey: boolean;
  model: string;
  temperature: number;
  maxTokens: number;
  contextWindow: number;
  thinkingBudget: string;
  searchProvider: string;
  hasSearchKey: boolean;
  subagentModels: Record<string, string>;
  enrichmentModel: string;
  enrichmentSystemPrompt: string;
  enrichmentDefaultPrompt: string;
}

function snapshotEqual(a: ConfigSnapshot, b: ConfigSnapshot): boolean {
  if (
    a.backend !== b.backend ||
    a.baseUrl !== b.baseUrl ||
    a.model !== b.model ||
    a.temperature !== b.temperature ||
    a.maxTokens !== b.maxTokens ||
    a.contextWindow !== b.contextWindow ||
    a.thinkingBudget !== b.thinkingBudget ||
    a.searchProvider !== b.searchProvider ||
    a.enrichmentModel !== b.enrichmentModel ||
    a.enrichmentSystemPrompt !== b.enrichmentSystemPrompt
  ) return false;
  // Treat a missing key and an empty-string value as equivalent —
  // the server strips empty subagent entries, so {} and {"code-reviewer": ""}
  // mean the same thing (no override set).
  const allKeys = new Set([
    ...Object.keys(a.subagentModels),
    ...Object.keys(b.subagentModels),
  ]);
  return [...allKeys].every(
    (k) => (a.subagentModels[k] || "") === (b.subagentModels[k] || "")
  );
}

/** Parse raw server config into a typed ConfigSnapshot. */
function parseSnapshot(cfg: Record<string, unknown>): ConfigSnapshot {
  return {
    backend: typeof cfg.backend_type === "string" ? cfg.backend_type : "openai",
    baseUrl: typeof cfg.base_url === "string" ? cfg.base_url : "",
    hasApiKey: !!cfg.has_api_key,
    model: typeof cfg.model === "string" ? cfg.model : "",
    temperature: cfg.temperature != null ? Number(cfg.temperature) : 0.2,
    maxTokens: cfg.max_tokens != null ? Number(cfg.max_tokens) : 16384,
    contextWindow: cfg.context_window != null ? Number(cfg.context_window) : 131072,
    thinkingBudget: cfg.thinking_budget != null ? String(cfg.thinking_budget) : "",
    searchProvider: typeof cfg.web_search_provider === "string" ? cfg.web_search_provider : "tavily",
    hasSearchKey: !!cfg.has_search_key,
    subagentModels: (cfg.subagent_models != null && typeof cfg.subagent_models === "object")
      ? { ...(cfg.subagent_models as Record<string, string>) }
      : {},
    enrichmentModel: typeof (cfg.prompt_enrichment as Record<string, unknown>)?.model === "string"
      ? (cfg.prompt_enrichment as Record<string, unknown>).model as string
      : "",
    enrichmentSystemPrompt: typeof (cfg.prompt_enrichment as Record<string, unknown>)?.system_prompt === "string"
      ? (cfg.prompt_enrichment as Record<string, unknown>).system_prompt as string
      : "",
    enrichmentDefaultPrompt: typeof (cfg.prompt_enrichment as Record<string, unknown>)?.default_system_prompt === "string"
      ? (cfg.prompt_enrichment as Record<string, unknown>).default_system_prompt as string
      : "",
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
  const [searchProvider, setSearchProvider] = useState("tavily");
  const [searchKey, setSearchKey] = useState("");
  const [hasSearchKey, setHasSearchKey] = useState(false);
  const [subagentModels, setSubagentModels] = useState<Record<string, string>>({});
  const [showSubagents, setShowSubagents] = useState(true);
  const [sameModel, setSameModel] = useState(false);
  const [enrichmentModel, setEnrichmentModel] = useState("");
  const [enrichmentSystemPrompt, setEnrichmentSystemPrompt] = useState("");
  const [enrichmentDefaultPrompt, setEnrichmentDefaultPrompt] = useState("");
  const [showEnrichment, setShowEnrichment] = useState(true);
  const [enrichmentDropdownOpen, setEnrichmentDropdownOpen] = useState(false);
  const [fetchStatus, setFetchStatus] = useState("");

  // ── Save / notification state ────────────────────────────────────────────────
  const [isSaving, setIsSaving] = useState(false);
  const [notificationDismissed, setNotificationDismissed] = useState(false);

  // Last snapshot committed to disk — basis for dirty-checking and cancel reset.
  const savedSnapshot = useRef<ConfigSnapshot | null>(null);
  // Base URL used for the last model fetch — triggers re-fetch when provider changes.
  const modelsBaseUrlRef = useRef<string>("");

  // ── Typeahead state ──────────────────────────────────────────────────────────
  const [modelListOpen, setModelListOpen] = useState(false);
  const [activeSubagentDropdown, setActiveSubagentDropdown] = useState<string | null>(null);
  const hideTimerRef = useRef<ReturnType<typeof setTimeout> | null>(null);

  // ── Hydrate form from server ─────────────────────────────────────────────────
  // Request config on mount.
  useEffect(() => {
    postMessage({ type: "getConfig" });
  }, [postMessage]);

  // Apply incoming configData — hydrates the form and resets the dirty baseline.
  // Skipped while a save is in flight so the ACK-triggered re-request doesn't
  // overwrite the form mid-save.
  // Auto-fetches models on first load if not already cached.
  useEffect(() => {
    if (!configData) return;
    if (isSaving) return;
    const snap = parseSnapshot(configData);
    savedSnapshot.current = snap;
    applySnapshot(snap);
    // Auto-fetch models if not cached or if base URL changed (e.g. provider switch)
    const urlChanged = snap.baseUrl && snap.baseUrl !== modelsBaseUrlRef.current;
    if (snap.baseUrl && (!configModels || urlChanged)) {
      const key = snap.hasApiKey ? "__use_stored__" : "";
      postMessage({ type: "listModels", backend: snap.backend, base_url: snap.baseUrl, api_key: key });
      modelsBaseUrlRef.current = snap.baseUrl;
      setFetchStatus("Fetching...");
    }
  }, [configData, isSaving]);

  /** Apply a snapshot to all form fields (shared by hydration and cancel). */
  function applySnapshot(snap: ConfigSnapshot) {
    setBackend(snap.backend);
    setBaseUrl(snap.baseUrl);
    setHasApiKey(snap.hasApiKey);
    setApiKey(snap.hasApiKey ? KEY_STORED_SENTINEL : "");
    setModel(snap.model);
    setTemperature(snap.temperature);
    setMaxTokens(snap.maxTokens);
    setContextWindow(snap.contextWindow);
    setThinkingBudget(snap.thinkingBudget);
    setSearchProvider(snap.searchProvider);
    setHasSearchKey(snap.hasSearchKey);
    setSearchKey(snap.hasSearchKey ? KEY_STORED_SENTINEL : "");
    setSubagentModels({ ...snap.subagentModels });
    setSameModel(deriveSameModel(snap, configSubagentNames));
    setEnrichmentModel(snap.enrichmentModel);
    setEnrichmentSystemPrompt(snap.enrichmentSystemPrompt);
    setEnrichmentDefaultPrompt(snap.enrichmentDefaultPrompt);
    // Restore fetch status from cached models (if available from a previous Fetch)
    if (configModels && !configModels.error && configModels.models.length > 0) {
      setFetchStatus(configModels.models.length + " model(s)");
    } else {
      setFetchStatus("");
    }
  }

  // ── Round-trip completion ────────────────────────────────────────────────────
  // When the server ACKs the save, clear the saving state and re-request the
  // config. The fresh config_loaded response will rehydrate savedSnapshot from
  // the actual persisted values, which resets the dirty baseline correctly.
  useEffect(() => {
    if (!configNotification) return;
    setNotificationDismissed(false);
    setIsSaving(false);
    if (configNotification.success) {
      postMessage({ type: "getConfig" });
    }
    const timer = setTimeout(() => setNotificationDismissed(true), 4000);
    return () => clearTimeout(timer);
  }, [configNotification, postMessage]);

  // ── Dirty tracking ───────────────────────────────────────────────────────────
  const currentSnapshot = useMemo<ConfigSnapshot>(() => ({
    backend,
    baseUrl,
    hasApiKey,
    model,
    temperature,
    maxTokens,
    contextWindow,
    thinkingBudget,
    searchProvider,
    hasSearchKey,
    subagentModels,
    enrichmentModel,
    enrichmentSystemPrompt,
    enrichmentDefaultPrompt,
  }), [backend, baseUrl, hasApiKey, model, temperature, maxTokens, contextWindow, thinkingBudget, searchProvider, hasSearchKey, subagentModels, enrichmentModel, enrichmentSystemPrompt, enrichmentDefaultPrompt]);

  const isDirty = useMemo(() => {
    if (!savedSnapshot.current) return false;
    return !snapshotEqual(currentSnapshot, savedSnapshot.current);
  }, [currentSnapshot]);

  // ── Backend change ───────────────────────────────────────────────────────────
  const handleBackendChange = useCallback((val: string) => {
    setBackend(val);
    if (val === "anthropic") setBaseUrl("");
  }, []);

  // ── Fetch models ─────────────────────────────────────────────────────────────
  const handleFetchModels = useCallback(() => {
    setFetchStatus("Fetching...");
    modelsBaseUrlRef.current = baseUrl;
    postMessage({
      type: "listModels",
      backend,
      base_url: baseUrl,
      api_key: (apiKey && apiKey !== KEY_STORED_SENTINEL) ? apiKey : "__use_stored__",
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

  // ── Enrichment model typeahead ───────────────────────────────────────────────
  const filteredEnrichmentModels = useMemo(() => {
    const all = configModels?.models ?? [];
    if (all.length === 0) return [];
    const query = enrichmentModel.toLowerCase().trim();
    return query ? all.filter((m) => m.toLowerCase().includes(query)) : all;
  }, [configModels, enrichmentModel]);

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
    setIsSaving(true);

    // Keys are write-only: only include them if the user typed a new value.
    // Empty field means "no change" — the server keeps the existing stored key.
    const payload: Record<string, unknown> = {
      backend_type: snap.backend,
      base_url: snap.baseUrl,
      model: snap.model,
      temperature: snap.temperature,
      max_tokens: snap.maxTokens,
      context_window: snap.contextWindow,
      thinking_budget: snap.thinkingBudget || null,
      web_search_provider: snap.searchProvider,
      subagent_models: snap.subagentModels,
    };
    if (apiKey && apiKey !== KEY_STORED_SENTINEL) { payload.api_key = apiKey; }
    if (searchKey && searchKey !== KEY_STORED_SENTINEL) { payload.search_key = searchKey; }
    payload.prompt_enrichment = {
      model: enrichmentModel.trim(),
      system_prompt: enrichmentSystemPrompt.trim(),
    };
    postMessage({ type: "saveConfig", config: payload });
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
              onFocus={() => { if (apiKey === KEY_STORED_SENTINEL) setApiKey(""); }}
              onBlur={() => { if (apiKey === "" && hasApiKey) setApiKey(KEY_STORED_SENTINEL); }}
              placeholder="Enter new key to update"
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

          {/* Thinking Budget: supported by Anthropic and OpenAI-compatible backends */}
          <Field label="Thinking Budget (tokens)">
            <input
              className="form-input"
              type="text"
              value={thinkingBudget}
              onChange={(e) => setThinkingBudget(e.target.value)}
              placeholder="(leave empty to disable)"
            />
          </Field>

          {/* Web Search */}
          <div className="settings-section">
            <div className="settings-section-label">Web Search</div>
            <div className="form-row">
              <div style={{ flex: "0 0 140px" }}>
                <Field label="Provider">
                  <select className="form-input" value={searchProvider} onChange={(e) => setSearchProvider(e.target.value)}>
                    <option value="tavily">Tavily</option>
                  </select>
                </Field>
              </div>
              <div style={{ flex: 1 }}>
                <Field label={<>API Key <span className="form-label-hint">{hasSearchKey ? "(key stored)" : "(not set)"}</span></>}>
                  <input
                    className="form-input"
                    type="password"
                    value={searchKey}
                    onChange={(e) => setSearchKey(e.target.value)}
                    onFocus={() => { if (searchKey === KEY_STORED_SENTINEL) setSearchKey(""); }}
                    onBlur={() => { if (searchKey === "" && hasSearchKey) setSearchKey(KEY_STORED_SENTINEL); }}
                    placeholder="Enter new key to update"
                  />
                </Field>
              </div>
            </div>
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

          {/* Prompt Enrichment */}
          <div className="settings-section">
            <button
              className="disclosure-row"
              onClick={() => setShowEnrichment(!showEnrichment)}
            >
              <i className={`codicon codicon-chevron-${showEnrichment ? "down" : "right"}`} />
              <span className="settings-section-label" style={{ margin: 0 }}>Prompt Enrichment</span>
            </button>
            {showEnrichment && (
              <div style={{ paddingLeft: 8, paddingTop: 4 }}>
                <Field label="Model">
                  <div style={{ position: "relative" }}>
                    <div className="model-input-wrap">
                      <input
                        className="form-input"
                        type="text"
                        value={enrichmentModel}
                        onChange={(e) => {
                          setEnrichmentModel(e.target.value);
                          if (hasModels) setEnrichmentDropdownOpen(true);
                        }}
                        onFocus={() => { if (hasModels) setEnrichmentDropdownOpen(true); }}
                        onBlur={() => setTimeout(() => setEnrichmentDropdownOpen(false), 200)}
                        placeholder="(inherit from main model)"
                      />
                      {enrichmentModel && (
                        <button
                          className="model-clear-btn"
                          onMouseDown={(e) => {
                            e.preventDefault();
                            setEnrichmentModel("");
                            if (hasModels) setEnrichmentDropdownOpen(true);
                          }}
                          tabIndex={-1}
                          title="Clear"
                        >
                          <i className="codicon codicon-close" />
                        </button>
                      )}
                    </div>
                    {enrichmentDropdownOpen && filteredEnrichmentModels.length > 0 && (
                      <div
                        className="model-list sa-typeahead"
                        onMouseDown={(e) => e.preventDefault()}
                      >
                        {filteredEnrichmentModels.map((m) => (
                          <div
                            key={m}
                            className={`model-list-item${enrichmentModel === m ? " selected" : ""}`}
                            onClick={() => {
                              setEnrichmentModel(m);
                              setEnrichmentDropdownOpen(false);
                            }}
                            style={enrichmentModel === m ? {
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
                </Field>
                <Field label={
                  <span style={{ display: "flex", alignItems: "center", gap: 6 }}>
                    Enrichment Prompt
                    {enrichmentSystemPrompt && (
                      <button
                        className="model-clear-btn"
                        title="Reset to default"
                        onClick={() => setEnrichmentSystemPrompt("")}
                        tabIndex={-1}
                      >
                        Reset
                      </button>
                    )}
                  </span>
                }>
                  <textarea
                    className="form-textarea"
                    value={enrichmentSystemPrompt}
                    rows={6}
                    onChange={(e) => setEnrichmentSystemPrompt(e.target.value)}
                    placeholder={enrichmentDefaultPrompt || "(use built-in default)"}
                  />
                </Field>
              </div>
            )}
          </div>

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
