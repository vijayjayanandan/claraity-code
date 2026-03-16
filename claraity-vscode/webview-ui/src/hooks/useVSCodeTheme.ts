/**
 * React hook for detecting VS Code theme (dark/light/high-contrast).
 *
 * VS Code adds class "vscode-dark", "vscode-light", or "vscode-high-contrast"
 * to <body>. This hook observes mutations and returns the current theme.
 *
 * CSS var(--vscode-*) tokens update automatically -- this hook is only
 * needed if you need imperative theme awareness (e.g., chart colors).
 */
import { useState, useEffect } from "react";

export type ThemeKind = "vscode-dark" | "vscode-light" | "vscode-high-contrast";

function detectTheme(): ThemeKind {
  const body = document.body;
  if (body.classList.contains("vscode-light")) return "vscode-light";
  if (body.classList.contains("vscode-high-contrast"))
    return "vscode-high-contrast";
  return "vscode-dark";
}

export function useVSCodeTheme(): ThemeKind {
  const [theme, setTheme] = useState<ThemeKind>(detectTheme);

  useEffect(() => {
    const observer = new MutationObserver(() => {
      setTheme(detectTheme());
    });
    observer.observe(document.body, {
      attributes: true,
      attributeFilter: ["class"],
    });
    return () => observer.disconnect();
  }, []);

  return theme;
}
