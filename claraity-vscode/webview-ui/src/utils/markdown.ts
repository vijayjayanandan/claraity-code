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
/** Restrict DOMPurify to safe prose + code tags only. */
const PURIFY_CONFIG = {
  ALLOWED_TAGS: [
    // Block
    "p", "br", "hr", "blockquote", "pre", "div",
    // Headings
    "h1", "h2", "h3", "h4", "h5", "h6",
    // Inline
    "strong", "b", "em", "i", "u", "s", "del", "code", "kbd", "mark", "span", "sub", "sup",
    // Lists
    "ul", "ol", "li",
    // Tables (GFM)
    "table", "thead", "tbody", "tr", "th", "td",
    // Links (href only, no onclick)
    "a",
    // Details
    "details", "summary",
  ],
  ALLOWED_ATTR: ["href", "title", "class", "id", "target", "rel", "colspan", "rowspan", "align"],
  ALLOW_DATA_ATTR: false,
  RETURN_TRUSTED_TYPE: false,
};

export function renderMarkdown(text: string): string {
  if (!text) return "";
  try {
    const raw = marked.parse(text) as string;
    return DOMPurify.sanitize(raw, PURIFY_CONFIG) as string;
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
