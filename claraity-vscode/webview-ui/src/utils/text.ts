/**
 * Shared text utilities for the ClarAIty webview.
 */

/** Remove <project_context>...</project_context> blocks from display text. */
export function stripProjectContext(text: string): string {
  return text.replace(/<project_context>[\s\S]*?<\/project_context>\s*/g, "");
}
