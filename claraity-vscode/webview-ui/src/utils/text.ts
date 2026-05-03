/**
 * Shared text utilities for the ClarAIty webview.
 */

/**
 * Wrap all occurrences of `query` in the plain text `content` with <mark> tags.
 * Returns an array of React-safe segments: { text, highlight }.
 * Case-insensitive. Used to build highlighted search results.
 */
export function highlightMatches(
  content: string,
  query: string,
): Array<{ text: string; highlight: boolean }> {
  if (!query) return [{ text: content, highlight: false }];
  const q = query.toLowerCase();
  const segments: Array<{ text: string; highlight: boolean }> = [];
  let i = 0;
  const lower = content.toLowerCase();
  while (i < content.length) {
    const idx = lower.indexOf(q, i);
    if (idx === -1) {
      segments.push({ text: content.slice(i), highlight: false });
      break;
    }
    if (idx > i) segments.push({ text: content.slice(i, idx), highlight: false });
    segments.push({ text: content.slice(idx, idx + query.length), highlight: true });
    i = idx + query.length;
  }
  return segments;
}

/** Remove injected context blocks from display text. */
export function stripProjectContext(text: string): string {
  return text
    .replace(/<project_context>[\s\S]*?<\/project_context>\s*/g, "")
    .replace(/<attached_files>[\s\S]*?<\/attached_files>\s*/g, "")
    .trim();
}
