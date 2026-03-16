/**
 * Markdown rendering utilities.
 *
 * Uses marked for parsing and DOMPurify for sanitization.
 * Falls back to plain text escaping if libraries aren't available.
 */
import { marked } from "marked";
import DOMPurify from "dompurify";

// Configure marked for safe inline rendering
marked.setOptions({
  breaks: true,
  gfm: true,
});

/**
 * Render markdown string to sanitized HTML.
 */
export function renderMarkdown(text: string): string {
  if (!text) return "";
  try {
    const raw = marked.parse(text) as string;
    return DOMPurify.sanitize(raw);
  } catch {
    return escapeHtml(text);
  }
}

/**
 * Escape HTML special characters.
 */
export function escapeHtml(text: string): string {
  return text
    .replace(/&/g, "&amp;")
    .replace(/</g, "&lt;")
    .replace(/>/g, "&gt;")
    .replace(/"/g, "&quot;")
    .replace(/'/g, "&#039;");
}
