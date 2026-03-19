/**
 * Shared text utilities for the ClarAIty webview.
 */

/** Remove injected context blocks from display text. */
export function stripProjectContext(text: string): string {
  return text
    .replace(/<project_context>[\s\S]*?<\/project_context>\s*/g, "")
    .replace(/<attached_files>[\s\S]*?<\/attached_files>\s*/g, "")
    .trim();
}
