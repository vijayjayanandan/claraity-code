/**
 * Turn statistics display (tokens used, duration).
 */

interface TurnStatsProps {
  tokens: number;
  durationMs: number;
}

export function TurnStats({ tokens, durationMs }: TurnStatsProps) {
  const durationStr = durationMs > 0
    ? `${(durationMs / 1000).toFixed(1)}s`
    : "";

  return (
    <div className="turn-stats">
      {tokens.toLocaleString()} tokens
      {durationStr && ` | ${durationStr}`}
    </div>
  );
}
