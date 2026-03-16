/**
 * Auto-approve settings panel with checkboxes.
 */
import { useState } from "react";

interface AutoApprovePanelProps {
  autoApprove: { edit: boolean; execute: boolean; browser: boolean };
  onChange: (categories: { edit?: boolean; execute?: boolean; browser?: boolean }) => void;
}

export function AutoApprovePanel({ autoApprove, onChange }: AutoApprovePanelProps) {
  const [expanded, setExpanded] = useState(false);

  const activeCategories: string[] = [];
  if (autoApprove.edit) activeCategories.push("Edit");
  if (autoApprove.execute) activeCategories.push("Commands");
  if (autoApprove.browser) activeCategories.push("Browser");

  const summaryText = activeCategories.length > 0
    ? `Auto-approve: ${activeCategories.join(", ")}`
    : "Auto-approve";

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
        </div>
      )}
    </div>
  );
}
