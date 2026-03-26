/**
 * Auto-approve and iteration limit settings panel.
 */
import { useState, useEffect } from "react";
import type { LimitsData } from "../types";

interface AutoApprovePanelProps {
  autoApprove: { read: boolean; edit: boolean; execute: boolean; browser: boolean };
  onChange: (categories: { read?: boolean; edit?: boolean; execute?: boolean; browser?: boolean }) => void;
  limits: LimitsData;
  onSaveLimits: (limits: LimitsData) => void;
  onLoadLimits: () => void;
  lastIterations: number | null;
}

export function AutoApprovePanel({
  autoApprove, onChange, limits, onSaveLimits, onLoadLimits, lastIterations,
}: AutoApprovePanelProps) {
  const [expanded, setExpanded] = useState(false);
  const [draft, setDraft] = useState<LimitsData>(limits);

  useEffect(() => { setDraft(limits); }, [limits]);
  useEffect(() => { if (expanded) onLoadLimits(); }, [expanded]); // eslint-disable-line react-hooks/exhaustive-deps

  const activeCategories: string[] = [];
  if (autoApprove.read) activeCategories.push("Read");
  if (autoApprove.edit) activeCategories.push("Edit");
  if (autoApprove.execute) activeCategories.push("Commands");
  if (autoApprove.browser) activeCategories.push("Browser");

  // Build collapsed summary
  const categoryText = activeCategories.length > 0
    ? activeCategories.join(", ")
    : "None";
  let summaryText = `Auto-approve: ${categoryText}`;
  if (draft.iteration_limit_enabled) {
    const iterPart = lastIterations != null
      ? `Iter: ${lastIterations}/${draft.max_iterations}`
      : `Iter: ${draft.max_iterations}`;
    summaryText += ` | ${iterPart}`;
  }

  return (
    <div className="auto-approve-panel">
      <div className="auto-approve-header" onClick={() => setExpanded(!expanded)}>
        <span className={`auto-approve-summary ${activeCategories.length > 0 ? "has-active" : ""}`}>
          {summaryText}
        </span>
        <span>{expanded ? "-" : "+"}</span>
      </div>
      {expanded && (
        <div className="auto-approve-body">
          <div className="aa-section-label">
            Tools that run without asking for confirmation:
          </div>
          <label className="aa-row">
            <input
              type="checkbox"
              checked={autoApprove.read}
              onChange={(e) => onChange({ ...autoApprove, read: e.target.checked })}
            />
            Read files
          </label>
          <label className="aa-row">
            <input
              type="checkbox"
              checked={autoApprove.edit}
              onChange={(e) => onChange({ ...autoApprove, edit: e.target.checked })}
            />
            Edit files
          </label>
          <label className="aa-row">
            <input
              type="checkbox"
              checked={autoApprove.execute}
              onChange={(e) => onChange({ ...autoApprove, execute: e.target.checked })}
            />
            Run commands
          </label>
          <label className="aa-row">
            <input
              type="checkbox"
              checked={autoApprove.browser}
              onChange={(e) => onChange({ ...autoApprove, browser: e.target.checked })}
            />
            Browser tools
          </label>

          <div className="aa-section-label" style={{ marginTop: "6px" }}>
            Pause the agent after reaching the iteration limit:
          </div>
          <div className="aa-row">
            <input
              type="checkbox"
              checked={draft.iteration_limit_enabled}
              onChange={(e) => {
                const updated = { ...draft, iteration_limit_enabled: e.target.checked };
                setDraft(updated);
                onSaveLimits(updated);
              }}
            />
            <span>Iteration limit</span>
            {draft.iteration_limit_enabled && (
              <input
                type="number"
                min={1}
                value={draft.max_iterations}
                onChange={(e) => setDraft({ ...draft, max_iterations: Math.max(1, parseInt(e.target.value) || 1) })}
                onBlur={() => onSaveLimits(draft)}
                className="aa-iter-input"
              />
            )}
          </div>
        </div>
      )}
    </div>
  );
}
