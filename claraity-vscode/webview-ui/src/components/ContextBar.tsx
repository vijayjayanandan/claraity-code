/**
 * Context window usage indicator with progress bar and cost estimate.
 */

// Approximate pricing per 1M tokens (input/output blended average)
const MODEL_PRICING: Record<string, { per1M: number }> = {
  "gpt-4o":            { per1M: 7.50 },
  "gpt-4o-mini":       { per1M: 0.30 },
  "gpt-4-turbo":       { per1M: 20.00 },
  "gpt-4":             { per1M: 45.00 },
  "gpt-3.5-turbo":     { per1M: 1.00 },
  "o1":                { per1M: 30.00 },
  "o1-mini":           { per1M: 6.00 },
  "o3-mini":           { per1M: 2.20 },
  "claude-3-opus":     { per1M: 45.00 },
  "claude-3-sonnet":   { per1M: 9.00 },
  "claude-3-haiku":    { per1M: 0.65 },
  "claude-3.5-sonnet": { per1M: 9.00 },
  "claude-4-sonnet":   { per1M: 9.00 },
  "deepseek-chat":     { per1M: 0.27 },
  "deepseek-reasoner": { per1M: 1.10 },
  "kimi-k2":           { per1M: 0.60 },
};

function estimateCost(tokens: number, model: string): number | null {
  const key = Object.keys(MODEL_PRICING).find((k) =>
    model.toLowerCase().includes(k),
  );
  if (!key) return null;
  return (tokens / 1_000_000) * MODEL_PRICING[key].per1M;
}

function formatCost(cost: number | null): string {
  if (cost === null) return "";
  if (cost < 0.01) return ` ~$${cost.toFixed(4)}`;
  return ` ~$${cost.toFixed(2)}`;
}

import { memo } from "react";

interface ContextBarProps {
  used: number;
  limit: number;
  totalTokens: number;
  turnCount: number;
  modelName: string;
}

export const ContextBar = memo(function ContextBar({ used, limit, totalTokens, turnCount, modelName }: ContextBarProps) {
  const pct = limit > 0 ? Math.round((used / limit) * 100) : 0;
  const costStr = totalTokens > 0 ? formatCost(estimateCost(totalTokens, modelName)) : "";

  return (
    <div className="context-bar">
      <div className="stats">
        <span>{pct}% context ({used.toLocaleString()} / {limit.toLocaleString()} tokens)</span>
        {totalTokens > 0 && (
          <span>
            {totalTokens.toLocaleString()} tokens{costStr} | {turnCount} turn{turnCount !== 1 ? "s" : ""}
          </span>
        )}
      </div>
      <div
        className={`context-bar-fill ${
          pct >= 85 ? "context-fill-danger" : pct >= 60 ? "context-fill-warning" : "context-fill-ok"
        }`}
        style={{ width: `${pct}%` }}
      />
    </div>
  );
});
