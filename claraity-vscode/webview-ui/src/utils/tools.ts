/**
 * Tool display utilities.
 *
 * Tool icon mapping and primary argument extraction,
 * matching the inline HTML implementation.
 */

export const TOOL_ICONS: Record<string, string> = {
  read_file: "R",
  write_file: "W",
  edit_file: "E",
  run_command: ">",
  list_directory: "D",
  search_files: "?",
  clarify: "Q",
  plan: "P",
  delegate_task: "T",
  delegate_to_subagent: "SA",
};

/**
 * Extract the most relevant argument from a tool call for display.
 */
export function getPrimaryArg(
  toolName: string,
  args?: Record<string, unknown>,
): string {
  if (!args) return "";
  if (toolName === "run_command") return String(args.command || "");
  if (args.path) return String(args.path);
  if (args.file_path) return String(args.file_path);
  if (args.query) return String(args.query);
  if (args.directory) return String(args.directory);
  // Fallback: first short string value
  for (const v of Object.values(args)) {
    if (typeof v === "string" && v.length < 200) return v;
  }
  return "";
}

/**
 * Format duration in milliseconds to a human-readable string.
 */
export function formatDuration(ms: number): string {
  if (ms < 1000) return `${ms}ms`;
  return `${(ms / 1000).toFixed(1)}s`;
}
