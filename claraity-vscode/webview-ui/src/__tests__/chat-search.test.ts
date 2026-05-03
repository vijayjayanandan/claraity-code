/**
 * Tests for in-session chat search:
 *   - reducer: TOGGLE_SEARCH, SET_SEARCH_QUERY, CLOSE_SEARCH
 *   - highlightMatches utility
 *   - highlightSearchInHtml (inline in ChatHistory, tested via its logic here)
 */
import { describe, test, expect, beforeEach } from "vitest";
import { appReducer, initialState, resetTimelineCounter, type AppState, type Action } from "../state/reducer";
import { highlightMatches } from "../utils/text";

function reduce(action: Action, state: AppState = initialState): AppState {
  return appReducer(state, action);
}

beforeEach(() => {
  resetTimelineCounter();
});

// ============================================================================
// Reducer — search actions
// ============================================================================

describe("appReducer — Chat Search", () => {
  test("initial state has searchOpen=false and searchQuery=''", () => {
    expect(initialState.searchOpen).toBe(false);
    expect(initialState.searchQuery).toBe("");
  });

  test("TOGGLE_SEARCH opens search when closed", () => {
    const s = reduce({ type: "TOGGLE_SEARCH" });
    expect(s.searchOpen).toBe(true);
    expect(s.searchQuery).toBe("");
  });

  test("TOGGLE_SEARCH closes search when open and clears query", () => {
    const open = { ...initialState, searchOpen: true, searchQuery: "hello" };
    const s = reduce({ type: "TOGGLE_SEARCH" }, open);
    expect(s.searchOpen).toBe(false);
    expect(s.searchQuery).toBe("");
  });

  test("TOGGLE_SEARCH preserves existing query when opening", () => {
    // Opening: query should stay as-is (could have been partially typed before close)
    const closed = { ...initialState, searchOpen: false, searchQuery: "leftover" };
    const s = reduce({ type: "TOGGLE_SEARCH" }, closed);
    expect(s.searchOpen).toBe(true);
    // Query preserved when opening (was not cleared)
    expect(s.searchQuery).toBe("leftover");
  });

  test("SET_SEARCH_QUERY updates the query string", () => {
    const s = reduce({ type: "SET_SEARCH_QUERY", query: "react hooks" });
    expect(s.searchQuery).toBe("react hooks");
  });

  test("SET_SEARCH_QUERY replaces previous query", () => {
    const withQuery = { ...initialState, searchQuery: "old" };
    const s = reduce({ type: "SET_SEARCH_QUERY", query: "new" }, withQuery);
    expect(s.searchQuery).toBe("new");
  });

  test("SET_SEARCH_QUERY allows empty string", () => {
    const withQuery = { ...initialState, searchQuery: "something" };
    const s = reduce({ type: "SET_SEARCH_QUERY", query: "" }, withQuery);
    expect(s.searchQuery).toBe("");
  });

  test("CLOSE_SEARCH sets searchOpen=false and clears query", () => {
    const open = { ...initialState, searchOpen: true, searchQuery: "test query" };
    const s = reduce({ type: "CLOSE_SEARCH" }, open);
    expect(s.searchOpen).toBe(false);
    expect(s.searchQuery).toBe("");
  });

  test("CLOSE_SEARCH is a no-op when already closed", () => {
    const s = reduce({ type: "CLOSE_SEARCH" });
    expect(s.searchOpen).toBe(false);
    expect(s.searchQuery).toBe("");
  });

  test("search state is independent of other state fields", () => {
    const s = reduce({ type: "TOGGLE_SEARCH" });
    // Other fields should be unchanged
    expect(s.connected).toBe(initialState.connected);
    expect(s.timeline).toBe(initialState.timeline);
    expect(s.messages).toBe(initialState.messages);
  });
});

// ============================================================================
// highlightMatches utility
// ============================================================================

describe("highlightMatches", () => {
  test("returns single non-highlight segment when query is empty", () => {
    const result = highlightMatches("hello world", "");
    expect(result).toEqual([{ text: "hello world", highlight: false }]);
  });

  test("returns single non-highlight segment when no match", () => {
    const result = highlightMatches("hello world", "xyz");
    expect(result).toEqual([{ text: "hello world", highlight: false }]);
  });

  test("wraps a single match in the middle", () => {
    const result = highlightMatches("say hello there", "hello");
    expect(result).toEqual([
      { text: "say ", highlight: false },
      { text: "hello", highlight: true },
      { text: " there", highlight: false },
    ]);
  });

  test("is case-insensitive", () => {
    const result = highlightMatches("Hello World", "hello");
    expect(result[0]).toEqual({ text: "Hello", highlight: true });
  });

  test("wraps match at start of string", () => {
    const result = highlightMatches("hello there", "hello");
    expect(result[0]).toEqual({ text: "hello", highlight: true });
    expect(result[1]).toEqual({ text: " there", highlight: false });
  });

  test("wraps match at end of string", () => {
    const result = highlightMatches("say hello", "hello");
    expect(result[0]).toEqual({ text: "say ", highlight: false });
    expect(result[1]).toEqual({ text: "hello", highlight: true });
  });

  test("wraps entire string when it is the match", () => {
    const result = highlightMatches("hello", "hello");
    expect(result).toEqual([{ text: "hello", highlight: true }]);
  });

  test("wraps multiple non-overlapping matches", () => {
    const result = highlightMatches("foo bar foo", "foo");
    const highlights = result.filter((s) => s.highlight);
    expect(highlights).toHaveLength(2);
    expect(highlights[0].text).toBe("foo");
    expect(highlights[1].text).toBe("foo");
  });

  test("handles special regex characters in query safely", () => {
    // Should not throw or behave unexpectedly
    const result = highlightMatches("price: (100)", "(100)");
    const match = result.find((s) => s.highlight);
    expect(match?.text).toBe("(100)");
  });

  test("returns empty array for empty content", () => {
    const result = highlightMatches("", "hello");
    // No segments produced (loop exits immediately)
    expect(result).toEqual([]);
  });

  test("highlight segment preserves original casing from content", () => {
    const result = highlightMatches("HELLO world", "hello");
    const match = result.find((s) => s.highlight);
    // The highlight should use original text casing, not query casing
    expect(match?.text).toBe("HELLO");
  });
});

// ============================================================================
// highlightSearchInHtml logic (tested inline — mirrors ChatHistory.tsx impl)
// ============================================================================

/** Mirror of the highlightSearchInHtml helper in ChatHistory.tsx */
function highlightSearchInHtml(html: string, query: string): string {
  if (!query.trim()) return html;
  const escaped = query.replace(/[.*+?^${}()|[\]\\]/g, "\\$&");
  const re = new RegExp(`(?![^<]*>)(${escaped})`, "gi");
  return html.replace(re, '<mark class="search-highlight">$1</mark>');
}

describe("highlightSearchInHtml", () => {
  test("returns html unchanged when query is empty", () => {
    const html = "<p>hello world</p>";
    expect(highlightSearchInHtml(html, "")).toBe(html);
  });

  test("returns html unchanged when query is whitespace only", () => {
    const html = "<p>hello world</p>";
    expect(highlightSearchInHtml(html, "   ")).toBe(html);
  });

  test("wraps plain text match in mark tag", () => {
    const result = highlightSearchInHtml("<p>hello world</p>", "hello");
    expect(result).toContain('<mark class="search-highlight">hello</mark>');
  });

  test("is case-insensitive", () => {
    const result = highlightSearchInHtml("<p>Hello World</p>", "hello");
    expect(result).toContain('<mark class="search-highlight">Hello</mark>');
  });

  test("does not wrap matches inside HTML tag attributes", () => {
    // href contains the search term -- should not be wrapped
    const html = '<a href="/search?q=hello">click hello here</a>';
    const result = highlightSearchInHtml(html, "hello");
    // The attribute value should be unchanged
    expect(result).toContain('href="/search?q=hello"');
    // The text node match should be wrapped
    expect(result).toContain('<mark class="search-highlight">hello</mark>');
  });

  test("wraps multiple matches", () => {
    const result = highlightSearchInHtml("<p>foo and foo again</p>", "foo");
    const count = (result.match(/search-highlight/g) ?? []).length;
    expect(count).toBe(2);
  });

  test("handles special regex characters in query", () => {
    const result = highlightSearchInHtml("<p>cost: (100)</p>", "(100)");
    expect(result).toContain('<mark class="search-highlight">(100)</mark>');
  });
});
