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
 * Return the key used as the primary argument for display.
 * Returns null if no primary arg can be determined.
 */
export function getPrimaryArgKey(
  toolName: string,
  args?: Record<string, unknown>,
): string | null {
  if (!args) return null;
  if (toolName === "run_command") return args.command ? "command" : null;
  if (args.path) return "path";
  if (args.file_path) return "file_path";
  if (args.query) return "query";
  if (args.directory) return "directory";
  // Fallback: first short string key
  for (const [k, v] of Object.entries(args)) {
    if (typeof v === "string" && v.length < 200) return k;
  }
  return null;
}

/**
 * Extract the most relevant argument from a tool call for display.
 */
export function getPrimaryArg(
  toolName: string,
  args?: Record<string, unknown>,
): string {
  if (!args) return "";
  const key = getPrimaryArgKey(toolName, args);
  if (key && args[key] != null) return String(args[key]);
  return "";
}

/**
 * Format duration in milliseconds to a human-readable string.
 */
export function formatDuration(ms: number): string {
  if (ms < 1000) return `${ms}ms`;
  return `${(ms / 1000).toFixed(1)}s`;
}
