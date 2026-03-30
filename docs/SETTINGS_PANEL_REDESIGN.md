# ClarAIty Settings Panel Redesign - Implementation Plan

> **Purpose:** LLM-consumable implementation plan for rebuilding the VS Code extension settings panel, inspired by Roo Code's settings UI.
>
> **Status:** PLANNING
> **Created:** 2026-03-16
> **Reference:** Roo Code v3.51.1 settings screenshots analyzed

---

## EXECUTIVE SUMMARY

Replace the current flat, single-scroll ConfigPanel with a **left-nav + content-area settings page** containing 10 categorized tabs. This is a layout-first approach: Phase 1 builds the shell and migrates existing Provider settings, then subsequent phases add new tabs progressively.

**Current state:** One flat ConfigPanel.tsx (400 lines) with 10 form fields, accessed via gear icon, single-scroll layout.

**Target state:** Settings page with persistent left sidebar navigation (icon + label), content area on the right, 10 tabs, search across settings, always-visible Save button.

---

## ARCHITECTURE DECISIONS

### AD-1: React component structure
```
SettingsPanel.tsx          -- Shell: left-nav + content-area + header (Save/Search/Back)
  SettingsNav.tsx           -- Left sidebar with icon + label nav items
  SettingsContent.tsx       -- Router that renders the active tab component
    ProvidersTab.tsx         -- Migrated from current ConfigPanel.tsx
    ModesTab.tsx             -- New
    AutoApproveTab.tsx       -- New
    ContextTab.tsx           -- New
    TerminalTab.tsx          -- New
    PromptsTab.tsx           -- New
    UITab.tsx                -- New
    ExperimentalTab.tsx      -- New
    AboutTab.tsx             -- New
    SubagentsTab.tsx         -- Migrated from ConfigPanel subagent section
```

### AD-2: State management
Extend the existing reducer pattern. Add:
```typescript
// New state fields in AppState
settingsTab: string;              // Active tab ID ("providers" | "modes" | ...)
settingsData: SettingsData;       // All settings, loaded once, saved once
settingsDirty: boolean;           // Unsaved changes indicator
settingsSearch: string;           // Search filter text
```

### AD-3: Settings persistence split
Settings will be stored in TWO locations (matching current pattern):
- **`.claraity/config.yaml`** -- LLM config, context limits, agent behavior (Python agent reads this)
- **VS Code `settings.json`** -- Extension-specific settings (connection mode, UI preferences)
- **VS Code `SecretStorage`** -- API keys (existing pattern, no change)

### AD-4: Message protocol extension
New message types between webview <-> extension <-> Python agent:
```typescript
// Webview -> Extension
{ type: "getSettings" }                    // Load all settings (replaces getConfig)
{ type: "saveSettings", settings: {...} }  // Save all settings (replaces saveConfig)
{ type: "resetSettings" }                  // Reset to defaults
{ type: "exportSettings" }                 // Export settings JSON
{ type: "importSettings", data: string }   // Import settings JSON

// Extension -> Webview
{ type: "settings_loaded", settings: SettingsData }
{ type: "settings_saved", success: boolean, message: string }
```

### AD-5: Backward compatibility
- Keep `getConfig`/`saveConfig` protocol working during transition
- `SettingsData` is a superset of current `configData`
- Old inline HTML fallback will NOT be updated (deprecated path)

---

## PHASE 1: Settings Shell + Provider Tab Migration
**Goal:** Replace flat ConfigPanel with left-nav layout. Migrate all existing provider fields. No new features yet.

### Files to create:
```
claraity-vscode/webview-ui/src/components/settings/
  SettingsPanel.tsx       -- Main shell component
  SettingsNav.tsx         -- Left sidebar navigation
  SettingsContent.tsx     -- Tab content router
  ProvidersTab.tsx        -- Migrated provider settings
  SubagentsTab.tsx        -- Migrated subagent model overrides
  settings.types.ts       -- TypeScript interfaces for all settings
  settings.css            -- Settings-specific styles (extracted from index.css)
```

### Files to modify:
```
claraity-vscode/webview-ui/src/App.tsx
  - Change: activePanel === "config" renders SettingsPanel instead of ConfigPanel
  - Keep ConfigPanel.tsx alive but unused (delete in Phase 1 cleanup)

claraity-vscode/webview-ui/src/state/reducer.ts
  - Add: settingsTab state field
  - Add: SET_SETTINGS_TAB action
  - Keep existing CONFIG_LOADED/CONFIG_SAVED/MODELS_LIST actions (they still work)

claraity-vscode/webview-ui/src/index.css
  - Add: .settings-layout (flexbox: nav + content)
  - Add: .settings-nav, .settings-nav-item, .settings-nav-item--active
  - Add: .settings-content
  - Keep: existing .form-field, .form-input, .form-label classes (reuse in tabs)
```

### SettingsPanel.tsx structure:
```tsx
// Shell component
export const SettingsPanel: React.FC<SettingsPanelProps> = (props) => {
  const [activeTab, setActiveTab] = useState("providers");

  return (
    <div className="settings-layout">
      <div className="settings-header">
        <button className="back-button" onClick={props.onBack}>
          <i className="codicon codicon-arrow-left" />
        </button>
        <span className="settings-title">Settings</span>
        <div className="settings-header-actions">
          <button className="settings-search-btn" title="Search settings">
            <i className="codicon codicon-search" />
          </button>
          <button className="settings-save-btn primary-btn" onClick={handleSave}>
            Save
          </button>
        </div>
      </div>
      <div className="settings-body-layout">
        <SettingsNav activeTab={activeTab} onTabChange={setActiveTab} />
        <SettingsContent activeTab={activeTab} {...contentProps} />
      </div>
    </div>
  );
};
```

### SettingsNav.tsx structure:
```tsx
const NAV_ITEMS = [
  { id: "providers",    icon: "codicon-settings-gear", label: "Providers" },
  { id: "subagents",    icon: "codicon-symbol-namespace", label: "Subagents" },
  { id: "auto-approve", icon: "codicon-check-all",     label: "Auto-Approve" },
  { id: "context",      icon: "codicon-file-text",     label: "Context" },
  { id: "terminal",     icon: "codicon-terminal",      label: "Terminal" },
  { id: "prompts",      icon: "codicon-comment",       label: "Prompts" },
  { id: "ui",           icon: "codicon-layout",        label: "UI" },
  { id: "experimental", icon: "codicon-beaker",        label: "Experimental" },
  { id: "about",        icon: "codicon-info",          label: "About" },
];
```

### CSS layout (settings.css):
```css
.settings-layout {
  display: flex;
  flex-direction: column;
  height: 100%;
  overflow: hidden;
}

.settings-header {
  display: flex;
  align-items: center;
  padding: 8px 12px;
  border-bottom: 1px solid var(--app-border);
  gap: 8px;
}

.settings-title {
  font-size: 14px;
  font-weight: 600;
  flex: 1;
}

.settings-header-actions {
  display: flex;
  gap: 8px;
  align-items: center;
}

.settings-save-btn {
  padding: 4px 16px;
  border-radius: 4px;
  font-size: 12px;
  background: var(--vscode-button-background);
  color: var(--vscode-button-foreground);
  border: none;
  cursor: pointer;
}

.settings-body-layout {
  display: flex;
  flex: 1;
  overflow: hidden;
}

.settings-nav {
  width: 160px;
  min-width: 160px;
  border-right: 1px solid var(--app-border);
  overflow-y: auto;
  padding: 4px 0;
}

.settings-nav-item {
  display: flex;
  align-items: center;
  gap: 8px;
  padding: 8px 12px;
  cursor: pointer;
  font-size: 12px;
  color: var(--vscode-foreground);
  border-left: 3px solid transparent;
  transition: background 0.15s;
}

.settings-nav-item:hover {
  background: var(--vscode-list-hoverBackground);
}

.settings-nav-item--active {
  background: var(--vscode-list-activeSelectionBackground);
  color: var(--vscode-list-activeSelectionForeground);
  border-left-color: var(--vscode-focusBorder);
}

.settings-nav-item .codicon {
  font-size: 14px;
  width: 16px;
  text-align: center;
}

.settings-content {
  flex: 1;
  overflow-y: auto;
  padding: 16px 20px;
}

.settings-content h2 {
  font-size: 16px;
  font-weight: 600;
  margin: 0 0 4px 0;
  color: var(--vscode-foreground);
}

.settings-content .section-description {
  font-size: 12px;
  color: var(--vscode-descriptionForeground);
  margin-bottom: 16px;
}

/* Reuse existing .form-field, .form-label, .form-input, .form-label-hint */
```

### ProvidersTab.tsx:
Direct migration from ConfigPanel.tsx lines 185-320. Same fields:
- Backend selector (dropdown)
- Base URL (text)
- API Key (password) with "(key stored)" indicator
- Model (text + typeahead + Fetch button)
- Temperature (range slider)
- Max Tokens (number)
- Context Window (number)
- Thinking Budget (text, optional)
- Web Search Provider + API Key

**New additions from Roo Code inspiration:**
- Model info display below model field: context window, image support, pricing (read-only, from model metadata)
- "Enable streaming" checkbox (maps to existing config)
- "Enable reasoning effort" checkbox + dropdown (maps to thinking_budget)

### Phase 1 validation:
- [ ] Left nav renders with all tab labels and icons
- [ ] Clicking a tab highlights it and shows correct content
- [ ] Providers tab has all fields from current ConfigPanel
- [ ] Save/Cancel works identically to current behavior
- [ ] Back button returns to chat
- [ ] Subagents tab shows per-subagent model overrides
- [ ] No regressions in existing config load/save flow

---

## PHASE 2: Auto-Approve Tab
**Goal:** Expose tool approval settings in the UI. Backend already has `ToolGatingService` with approval checks.

### Auto-Approve tab fields:
```
Auto-Approve Enabled          [checkbox]
  When enabled, these tool categories run without asking for permission.

Tool categories (horizontal toggle bar):
  [Read] [Write] [Execute] [Plan] [Subagents]

Max iterations per turn:      [number input, default: 25]
  Maximum tool calls before pausing for user confirmation.

Max consecutive errors:       [slider 0-10, default: 3]
  Number of consecutive errors before stopping. Set to 0 to disable.
```

### Backend changes needed:
```python
# .claraity/config.yaml additions:
approval:
  auto_approve: false
  categories:
    read: true
    write: false
    execute: false
    plan: true
    subagents: false
  max_iterations: 25
  max_consecutive_errors: 3
```

### Files to modify:
```
src/core/tool_gating.py          -- Read approval config from config.yaml
src/server/config_handler.py     -- Include approval settings in get/save
claraity-vscode/webview-ui/src/components/settings/AutoApproveTab.tsx  -- New
claraity-vscode/webview-ui/src/components/settings/settings.types.ts   -- Add types
```

---

## PHASE 3: Context Tab
**Goal:** Let users control what goes into the AI's context window.

### Context tab fields:
```
--- Context Limits ---
Context window size:           [number input] (existing, moved here)
Max conversation history:      [slider 10-200, default: 50]
  Messages to keep before compaction.

--- Diagnostics ---
Auto-include diagnostics:      [checkbox, default: true]
  Include editor warnings/errors when discussing files.
Max diagnostic messages:       [slider 0-100, default: 50]

--- Context Condensing ---
Enable auto-compaction:        [checkbox, default: true]
Compaction threshold:          [slider 50%-100%, default: 80%]
  Compact when context usage exceeds this percentage.
```

### Backend changes needed:
```python
# .claraity/config.yaml additions:
context:
  max_history_messages: 50
  auto_include_diagnostics: true
  max_diagnostics: 50
  auto_compaction: true
  compaction_threshold: 0.8
```

### Files to modify:
```
src/memory/working_memory.py     -- Read context limits from config
src/server/config_handler.py     -- Include context settings in get/save
claraity-vscode/webview-ui/src/components/settings/ContextTab.tsx  -- New
```

---

## PHASE 4: Prompts Tab
**Goal:** Let users customize system prompt instructions and prompt enhancement templates.

### Prompts tab fields:
```
--- Custom Instructions ---
Custom system instructions:    [textarea, 6 rows]
  Added to the system prompt for every conversation.
  Instructions can also be placed in .claraity/instructions.md

--- Prompt Enhancement ---
Prompt type:                   [dropdown: Enhance Prompt, Explain Code, Fix Issues, Improve Code]
Enhancement template:          [textarea with ${userInput} variable]
API Configuration:             [dropdown: Use current | specific profile]
Include conversation history:  [checkbox, default: true]

[Preview Enhancement]          [button - sends test prompt]
Test input:                    [textarea for testing]
```

### Backend changes needed:
```python
# .claraity/config.yaml additions:
prompts:
  custom_instructions: ""
  enhancement_templates:
    enhance_prompt: "Generate an enhanced version of this prompt..."
    explain_code: "Explain this code clearly..."
    fix_issues: "Identify and fix issues in this code..."
    improve_code: "Suggest improvements for this code..."
```

### Files to modify:
```
src/prompts/system_prompts.py    -- Inject custom_instructions into system prompt
src/server/config_handler.py     -- Include prompts settings
claraity-vscode/webview-ui/src/components/settings/PromptsTab.tsx  -- New
```

---

## PHASE 5: UI + Terminal + Experimental Tabs
**Goal:** Expose UI preferences, terminal behavior, and experimental features.

### UI tab fields:
```
Collapse thinking by default:  [checkbox, default: true]
  Thinking blocks collapsed until clicked.

Send with Ctrl+Enter:          [checkbox, default: false]
  Require Ctrl+Enter instead of just Enter.

Show token usage:              [checkbox, default: true]
  Display token count in message footer.
```

### Terminal tab fields:
```
--- Terminal Settings ---
Command output preview size:   [dropdown: Small (5KB) | Medium (10KB) | Large (25KB)]
Shell type:                    [dropdown: Auto | bash | powershell | cmd]
Command timeout (seconds):     [slider 30-600, default: 120]
```

### Experimental tab fields:
```
Background editing:            [checkbox, default: false]
  File edits happen without opening diff views.

Enable custom tools:           [checkbox, default: false]
  Load tools from .claraity/tools/ directory.

Debug mode:                    [checkbox, default: false]
  Show raw API messages in conversation.
```

### Files to modify:
```
claraity-vscode/webview-ui/src/components/settings/UITab.tsx           -- New
claraity-vscode/webview-ui/src/components/settings/TerminalTab.tsx     -- New
claraity-vscode/webview-ui/src/components/settings/ExperimentalTab.tsx -- New
```

### Backend changes needed:
```python
# .claraity/config.yaml additions:
ui:
  collapse_thinking: true
  ctrl_enter_send: false
  show_token_usage: true

terminal:
  output_preview_size: "medium"   # small|medium|large
  shell_type: "auto"
  command_timeout: 120

experimental:
  background_editing: false
  custom_tools: false
  debug_mode: false
```

---

## PHASE 6: About Tab + Settings Management
**Goal:** Version info, export/import/reset settings.

### About tab fields:
```
--- About ClarAIty ---
Version: {version from package.json}
Agent Version: {version from Python package}

--- Manage Settings ---
[Export]  [Import]  [Reset]     -- Three action buttons

Export: Downloads settings as JSON
Import: File picker to load JSON
Reset: Confirmation dialog, then restore defaults

--- Debug ---
Enable debug mode:             [checkbox]
View session logs:             [link button -> opens log file]
```

### Files to modify:
```
claraity-vscode/webview-ui/src/components/settings/AboutTab.tsx  -- New
claraity-vscode/src/sidebar-provider.ts  -- Handle export/import/reset messages
```

---

## PHASE 7: Search Across Settings
**Goal:** Search input in header that filters visible settings across all tabs.

### Implementation:
```typescript
// Each tab registers its searchable fields
const SEARCHABLE_FIELDS: SearchField[] = [
  { tab: "providers", label: "Backend", keywords: ["provider", "openai", "ollama", "anthropic"] },
  { tab: "providers", label: "API Key", keywords: ["key", "authentication", "secret"] },
  { tab: "providers", label: "Model", keywords: ["model", "llm", "gpt", "claude"] },
  { tab: "providers", label: "Temperature", keywords: ["temperature", "randomness", "creativity"] },
  // ... all fields
];

// Search flow:
// 1. User types in search box
// 2. Filter SEARCHABLE_FIELDS by query match
// 3. If matches span multiple tabs, show flat list with tab badges
// 4. If matches are in one tab, switch to that tab and highlight matching fields
```

---

## SHARED UI COMPONENTS

### Form primitives to extract (reusable across all tabs):
```tsx
// components/settings/shared/
FormField.tsx       -- Label + hint + children wrapper
FormInput.tsx       -- Text/number/password input with validation
FormSelect.tsx      -- Dropdown select
FormCheckbox.tsx    -- Checkbox with label and description
FormSlider.tsx      -- Range slider with value display
FormTextarea.tsx    -- Multiline text input
FormSection.tsx     -- Collapsible section with header
FormToggleBar.tsx   -- Horizontal toggle buttons (like auto-approve categories)
```

### FormSlider example:
```tsx
interface FormSliderProps {
  label: string;
  hint?: string;
  min: number;
  max: number;
  step?: number;
  value: number;
  unit?: string;          // "s", "ms", "%", "KB"
  onChange: (value: number) => void;
}

export const FormSlider: React.FC<FormSliderProps> = ({
  label, hint, min, max, step = 1, value, unit = "", onChange
}) => (
  <div className="form-field">
    <label className="form-label">{label}</label>
    {hint && <span className="form-label-hint">{hint}</span>}
    <div className="slider-row">
      <input type="range" min={min} max={max} step={step}
             value={value} onChange={e => onChange(Number(e.target.value))} />
      <span className="slider-value">{value}{unit}</span>
    </div>
  </div>
);
```

### FormCheckbox example:
```tsx
interface FormCheckboxProps {
  label: string;
  description?: string;
  checked: boolean;
  onChange: (checked: boolean) => void;
}

export const FormCheckbox: React.FC<FormCheckboxProps> = ({
  label, description, checked, onChange
}) => (
  <div className="form-field form-checkbox-field">
    <label className="checkbox-label">
      <input type="checkbox" checked={checked}
             onChange={e => onChange(e.target.checked)} />
      <span className="checkbox-text">{label}</span>
    </label>
    {description && <span className="form-label-hint checkbox-description">{description}</span>}
  </div>
);
```

---

## INLINE HTML FALLBACK STRATEGY

The current inline HTML settings panel in sidebar-provider.ts (lines 4436-4700+) will NOT be updated during this redesign. It is a deprecated fallback for the rare case where the React build is missing.

**Decision:** After Phase 1 is stable, remove the inline HTML config panel entirely. The React build is always present in production bundles.

---

## SETTINGS DATA TYPES (settings.types.ts)

```typescript
export interface ProviderSettings {
  backend_type: "openai" | "ollama" | "anthropic";
  base_url: string;
  model: string;
  temperature: number;
  max_tokens: number;
  context_window: number;
  thinking_budget: string;
  has_api_key: boolean;
  search_provider: string;
  has_search_key: boolean;
  enable_streaming: boolean;
  enable_reasoning: boolean;
}

export interface SubagentSettings {
  use_same_model: boolean;
  overrides: Record<string, string>;  // subagent_name -> model
}

export interface ApprovalSettings {
  auto_approve: boolean;
  categories: {
    read: boolean;
    write: boolean;
    execute: boolean;
    plan: boolean;
    subagents: boolean;
  };
  max_iterations: number;
  max_consecutive_errors: number;
}

export interface ContextSettings {
  max_history_messages: number;
  auto_include_diagnostics: boolean;
  max_diagnostics: number;
  auto_compaction: boolean;
  compaction_threshold: number;
}

export interface PromptSettings {
  custom_instructions: string;
  enhancement_templates: Record<string, string>;
}

export interface UISettings {
  collapse_thinking: boolean;
  ctrl_enter_send: boolean;
  show_token_usage: boolean;
}

export interface TerminalSettings {
  output_preview_size: "small" | "medium" | "large";
  shell_type: "auto" | "bash" | "powershell" | "cmd";
  command_timeout: number;
}

export interface ExperimentalSettings {
  background_editing: boolean;
  custom_tools: boolean;
  debug_mode: boolean;
}

export interface SettingsData {
  provider: ProviderSettings;
  subagents: SubagentSettings;
  approval: ApprovalSettings;
  context: ContextSettings;
  prompts: PromptSettings;
  ui: UISettings;
  terminal: TerminalSettings;
  experimental: ExperimentalSettings;
}

export type SettingsTab =
  | "providers"
  | "subagents"
  | "auto-approve"
  | "context"
  | "terminal"
  | "prompts"
  | "ui"
  | "experimental"
  | "about";

export interface NavItem {
  id: SettingsTab;
  icon: string;
  label: string;
}
```

---

## IMPLEMENTATION ORDER & DEPENDENCIES

```
Phase 1 (Settings Shell + Providers)
  |- No backend changes needed
  |- Pure frontend restructure
  |- Estimated files: 8 new, 3 modified
  |
Phase 2 (Auto-Approve)
  |- Requires: config.yaml schema extension
  |- Requires: tool_gating.py reads from config
  |- Estimated files: 1 new component, 2 backend modifications
  |
Phase 3 (Context)
  |- Requires: config.yaml schema extension
  |- Requires: working_memory.py reads limits from config
  |- Estimated files: 1 new component, 2 backend modifications
  |
Phase 4 (Prompts)
  |- Requires: config.yaml schema extension
  |- Requires: system_prompts.py reads custom instructions
  |- Estimated files: 1 new component, 2 backend modifications
  |
Phase 5 (UI + Terminal + Experimental)
  |- Mix of frontend-only (UI tab) and backend (terminal, experimental)
  |- Estimated files: 3 new components, 2 backend modifications
  |
Phase 6 (About + Settings Management)
  |- Frontend only (export/import/reset)
  |- Estimated files: 1 new component, 1 extension modification
  |
Phase 7 (Search)
  |- Frontend only, search index across all tabs
  |- Estimated files: 1 new component, modify SettingsPanel.tsx
```

---

## KEY CONSTRAINTS

1. **No emojis in TypeScript/Python code** -- Windows cp1252 encoding constraint
2. **VS Code theme compliance** -- All colors via `--vscode-*` CSS variables
3. **Codicon icons only** -- No custom SVGs, use VS Code's built-in codicon font
4. **SecretStorage for API keys** -- Never persist secrets to config.yaml
5. **SSRF validation** -- All URLs validated before outbound requests (existing pattern)
6. **Backward compatibility** -- Old `getConfig`/`saveConfig` must keep working until Phase 1 is fully validated
7. **No console.log in production** -- Use VS Code output channel or remove
8. **Single writer pattern** -- Config.yaml writes go through config_handler.py only

---

## EXISTING CODE REFERENCES

| What | File | Lines |
|------|------|-------|
| Current ConfigPanel | `claraity-vscode/webview-ui/src/components/ConfigPanel.tsx` | 1-400 |
| Panel routing | `claraity-vscode/webview-ui/src/App.tsx` | 134-148 |
| Config state/actions | `claraity-vscode/webview-ui/src/state/reducer.ts` | 327-335, 934-954 |
| Extension message handlers | `claraity-vscode/src/sidebar-provider.ts` | 467-511 |
| Settings CSS | `claraity-vscode/webview-ui/src/index.css` | 1349-1507 |
| StatusBar gear icon | `claraity-vscode/webview-ui/src/components/StatusBar.tsx` | 26-28 |
| Python config handler | `src/server/config_handler.py` | 1-253 |
| Agent config file | `.claraity/config.yaml` | 1-36 |
| Tool gating service | `src/core/tool_gating.py` | 1-289 |
| Working memory | `src/memory/working_memory.py` | Full file |
| System prompts | `src/prompts/system_prompts.py` | Full file |

---

## ROO CODE FEATURE MAPPING

Which Roo Code features we adopt vs skip:

| Roo Code Feature | Our Plan | Why |
|-----------------|----------|-----|
| Left-nav layout | Phase 1 | Core UX improvement |
| Configuration profiles | SKIP for now | Over-engineering for our user base |
| Provider settings | Phase 1 (migrate) | Already have this |
| Modes/Personas | SKIP | We have Plan/Act; full modes is a separate epic |
| Skills management | SKIP | Already planned separately (see memory: skill-system-plan.md) |
| Slash commands | SKIP | Not applicable to our architecture yet |
| Auto-Approve | Phase 2 | High value, backend exists |
| MCP Servers | SKIP | We don't have MCP support yet |
| Checkpoints | SKIP | Not implemented in our agent |
| Notifications (TTS/sound) | SKIP | Low value |
| Context controls | Phase 3 | High value for token management |
| Terminal settings | Phase 5 | Medium value |
| Prompts/enhancement | Phase 4 | High value, differentiator |
| Worktrees | SKIP | Git worktree is a separate feature |
| UI preferences | Phase 5 | Low effort, nice polish |
| Experimental flags | Phase 5 | Useful for feature gating |
| Language selection | SKIP | Not needed for single-language app |
| About page | Phase 6 | Essential for settings management |
| Search across settings | Phase 7 | Polish feature, do last |
| Export/Import/Reset | Phase 6 | High value for setup portability |
