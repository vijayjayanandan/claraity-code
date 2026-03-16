/**
 * LLM configuration settings panel.
 *
 * Full feature parity with inline HTML: backend selector, base URL,
 * API key with stored indicator, model with fetch/list/typeahead,
 * temperature, max tokens, context window, thinking budget,
 * web search config, subagent models with typeahead,
 * save/cancel with notification feedback.
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

export function ConfigPanel({
  postMessage,
  onBack,
  configData,
  configSubagentNames,
  configModels,
  configNotification,
}: ConfigPanelProps) {
  // Local form state
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
  const [showSubagents, setShowSubagents] = useState(false);
  const [sameModel, setSameModel] = useState(false);
  const [fetchStatus, setFetchStatus] = useState("");

  // Typeahead visibility state
  const [modelListOpen, setModelListOpen] = useState(false);
  const [activeSubagentDropdown, setActiveSubagentDropdown] = useState<string | null>(null);
  const hideTimerRef = useRef<ReturnType<typeof setTimeout> | null>(null);

  // Request config on mount
  useEffect(() => {
    postMessage({ type: "getConfig" });
  }, [postMessage]);

  // Populate form when config arrives
  useEffect(() => {
    if (!configData) return;
    const cfg = (configData as Record<string, unknown>) ?? {};
    setBackend((cfg.backend_type as string) || "openai");
    setBaseUrl((cfg.base_url as string) || "");
    setApiKey((cfg.api_key as string) || "");
    setHasApiKey(!!cfg.has_api_key);
    setModel((cfg.model as string) || "");
    setTemperature(cfg.temperature != null ? Number(cfg.temperature) : 0.2);
    setMaxTokens(cfg.max_tokens != null ? Number(cfg.max_tokens) : 16384);
    setContextWindow(cfg.context_window != null ? Number(cfg.context_window) : 131072);
    setThinkingBudget(cfg.thinking_budget != null ? String(cfg.thinking_budget) : "");
    setSearchKey((cfg.search_key as string) || "");
    setHasSearchKey(!!cfg.has_search_key);
    const saModels = (cfg.subagent_models as Record<string, string>) ?? {};
    setSubagentModels(saModels);
    setFetchStatus("");
  }, [configData]);

  // Auto-close on successful save after 3 seconds
  useEffect(() => {
    if (configNotification?.success) {
      const timer = setTimeout(onBack, 3000);
      return () => clearTimeout(timer);
    }
  }, [configNotification, onBack]);

  // Backend change -> auto-suggest URL
  const handleBackendChange = useCallback((val: string) => {
    setBackend(val);
    if (val === "ollama") setBaseUrl("http://localhost:11434");
    else if (val === "anthropic") setBaseUrl("");
  }, []);

  const handleFetchModels = useCallback(() => {
    setFetchStatus("Fetching...");
    postMessage({ type: "listModels", backend, base_url: baseUrl, api_key: apiKey });
  }, [backend, baseUrl, apiKey, postMessage]);

  // Update fetch status when models arrive
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

  // Filtered model list for typeahead (G3)
  const filteredModels = useMemo(() => {
    const all = configModels?.models ?? [];
    if (all.length === 0) return [];
    const query = model.toLowerCase().trim();
    return query ? all.filter((m) => m.toLowerCase().includes(query)) : all;
  }, [configModels, model]);

  const handleSameModel = useCallback((checked: boolean) => {
    setSameModel(checked);
    if (checked) {
      const updated: Record<string, string> = {};
      for (const name of configSubagentNames) updated[name] = model;
      setSubagentModels(updated);
    }
  }, [model, configSubagentNames]);

  const handleSave = useCallback(() => {
    const saModels: Record<string, string> = {};
    for (const name of configSubagentNames) {
      const val = subagentModels[name]?.trim();
      if (val) saModels[name] = val;
    }
    postMessage({
      type: "saveConfig",
      config: {
        backend_type: backend,
        base_url: baseUrl,
        api_key: apiKey,
        model,
        temperature,
        max_tokens: maxTokens,
        context_window: contextWindow,
        thinking_budget: thinkingBudget || null,
        subagent_models: saModels,
        search_key: searchKey,
      },
    });
  }, [backend, baseUrl, apiKey, model, temperature, maxTokens, contextWindow, thinkingBudget, searchKey, subagentModels, configSubagentNames, postMessage]);

  // Helpers for delayed hide (matches inline HTML's 200ms blur delay)
  const scheduleHideModelList = useCallback(() => {
    hideTimerRef.current = setTimeout(() => setModelListOpen(false), 200);
  }, []);
  const cancelHideModelList = useCallback(() => {
    if (hideTimerRef.current) clearTimeout(hideTimerRef.current);
  }, []);

  // Subagent typeahead: filter models for a given subagent input value
  const filteredSubagentModels = useCallback((name: string) => {
    const all = configModels?.models ?? [];
    if (all.length === 0) return [];
    const query = (subagentModels[name] || "").toLowerCase().trim();
    const filtered = query ? all.filter((m) => m.toLowerCase().includes(query)) : all;
    return filtered;
  }, [configModels, subagentModels]);

  return (
    <div className="session-panel">
      <div className="session-panel-header">
        <button className="btn-secondary" onClick={onBack}>
          <i className="codicon codicon-arrow-left" /> Back
        </button>
        <span className="settings-header-title">Settings</span>
        <div />
      </div>

      <div className="settings-body">
        {/* Notification */}
        {configNotification && (
          <div className={`notification-banner ${configNotification.success ? "success" : "error"}`}>
            {configNotification.message}
          </div>
        )}

        {/* Backend */}
        <Field label="Backend">
          <select className="form-input" value={backend} onChange={(e) => handleBackendChange(e.target.value)}>
            <option value="openai">OpenAI-compatible</option>
            <option value="ollama">Ollama</option>
            <option value="anthropic">Anthropic</option>
          </select>
        </Field>

        {/* Base URL */}
        <Field label="Base URL">
          <input
            className="form-input"
            type="text"
            value={baseUrl}
            onChange={(e) => setBaseUrl(e.target.value)}
            placeholder="https://api.openai.com/v1"
          />
        </Field>

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

        {/* Model with typeahead (G3) */}
        <Field label="Model">
          <div className="form-row" style={{ marginBottom: 4 }}>
            <input
              className="form-input"
              type="text"
              value={model}
              onChange={(e) => setModel(e.target.value)}
              onFocus={() => { if ((configModels?.models.length ?? 0) > 0) setModelListOpen(true); }}
              onBlur={scheduleHideModelList}
              placeholder="gpt-4o"
              style={{ flex: 1 }}
            />
            <button className="btn-secondary" onClick={handleFetchModels} style={{ whiteSpace: "nowrap" }}>
              Fetch
            </button>
          </div>
          {fetchStatus && <div className="form-label-hint" style={{ marginBottom: 4 }}>{fetchStatus}</div>}
          {modelListOpen && filteredModels.length > 0 && (
            <div
              className="model-list"
              onMouseDown={(e) => e.preventDefault()}
            >
              {filteredModels.map((m) => (
                <div
                  key={m}
                  className={`model-list-item${m === model ? " selected" : ""}`}
                  onClick={() => {
                    setModel(m);
                    setModelListOpen(false);
                    cancelHideModelList();
                  }}
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

        {/* Thinking Budget */}
        <Field label="Thinking Budget (tokens)">
          <input
            className="form-input"
            type="text"
            value={thinkingBudget}
            onChange={(e) => setThinkingBudget(e.target.value)}
            placeholder="(leave empty for default)"
          />
        </Field>

        {/* Web Search (G1) */}
        <div className="form-field" style={{ borderTop: "1px solid var(--app-border)", marginTop: 8, paddingTop: 6 }}>
          <label className="form-label" style={{ fontWeight: 600 }}>Web Search</label>
          <Field label="Search Provider">
            <select className="form-input" defaultValue="tavily">
              <option value="tavily">Tavily</option>
            </select>
          </Field>
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

        {/* Subagent Models with typeahead (G4) */}
        {configSubagentNames.length > 0 && (
          <div className="form-field">
            <button
              className="btn-secondary"
              onClick={() => setShowSubagents(!showSubagents)}
              style={{ marginBottom: 4 }}
            >
              {showSubagents ? "- Subagent Models" : "+ Subagent Models"}
            </button>
            {showSubagents && (
              <div style={{ paddingLeft: 8 }}>
                <div style={{ marginBottom: 4 }}>
                  <label className="form-label" style={{ display: "flex", alignItems: "center", gap: 4, marginBottom: 0 }}>
                    <input
                      type="checkbox"
                      checked={sameModel}
                      onChange={(e) => handleSameModel(e.target.checked)}
                    />
                    Use main model for all subagents
                  </label>
                </div>
                {configSubagentNames.map((name) => (
                  <div key={name} style={{ marginBottom: 6, position: "relative" }}>
                    <label className="form-label">{name}</label>
                    <input
                      className="form-input"
                      type="text"
                      value={subagentModels[name] || ""}
                      onChange={(e) => setSubagentModels({ ...subagentModels, [name]: e.target.value })}
                      onFocus={() => { if ((configModels?.models.length ?? 0) > 0) setActiveSubagentDropdown(name); }}
                      onBlur={() => setTimeout(() => setActiveSubagentDropdown((cur) => cur === name ? null : cur), 200)}
                      placeholder="(inherit from main)"
                    />
                    {activeSubagentDropdown === name && filteredSubagentModels(name).length > 0 && (
                      <div
                        className="model-list sa-typeahead"
                        onMouseDown={(e) => e.preventDefault()}
                      >
                        {filteredSubagentModels(name).map((m) => (
                          <div
                            key={m}
                            className="model-list-item"
                            onClick={() => {
                              setSubagentModels({ ...subagentModels, [name]: m });
                              setActiveSubagentDropdown(null);
                            }}
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

        {/* Save / Cancel */}
        <div className="form-actions">
          <button className="btn-primary" onClick={handleSave}>Save</button>
          <button className="btn-secondary" onClick={onBack}>Cancel</button>
        </div>
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
