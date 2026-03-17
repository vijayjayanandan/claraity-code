/**
 * Entry point for the ClarAIty VS Code webview React app.
 *
 * Mounts the root <App /> component into the #root div
 * provided by the extension's getHtmlForWebview().
 */
import { StrictMode } from "react";
import { createRoot } from "react-dom/client";
import { App } from "./App";
import { ErrorBoundary } from "./components/ErrorBoundary";
import "./index.css";

// When running outside VS Code (Vite dev server / test harness),
// load dark theme fallbacks and the message injection helper.
if (typeof acquireVsCodeApi !== "function") {
  import("./test-harness/harness-theme.css");
  import("./test-harness/inject");
}

const rootEl = document.getElementById("root");
if (!rootEl) {
  throw new Error("Root element #root not found in webview HTML");
}

createRoot(rootEl).render(
  <StrictMode>
    <ErrorBoundary>
      <App />
    </ErrorBoundary>
  </StrictMode>,
);
