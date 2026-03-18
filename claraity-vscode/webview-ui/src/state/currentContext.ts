/**
 * Module-level tracker for the current session context.
 *
 * ErrorBoundary is mounted outside the React tree that has access to
 * Redux/useReducer state, so it reads session info from here instead.
 * Updated by App.tsx whenever the session changes.
 */

let _sessionId = "";

export function setCurrentSessionId(id: string): void {
  _sessionId = id;
}

export function getCurrentSessionId(): string {
  return _sessionId;
}
