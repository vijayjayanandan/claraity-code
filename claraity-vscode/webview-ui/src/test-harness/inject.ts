/**
 * Global helpers for injecting messages into the webview from
 * Playwright tests or the browser console.
 *
 * Exposes:
 *   window.__clarityInject(msg)          — inject a single ExtensionMessage
 *   window.__clarityInjectSequence(seq)  — inject a sequence with optional delays
 */
import type { ExtensionMessage } from "../types";

declare global {
  interface Window {
    __clarityInject: (msg: ExtensionMessage) => void;
    __clarityInjectSequence: (
      seq: Array<{ msg: ExtensionMessage; delayMs?: number }>,
    ) => Promise<void>;
  }
}

window.__clarityInject = (msg: ExtensionMessage) => {
  window.postMessage(msg, "*");
};

window.__clarityInjectSequence = async (
  seq: Array<{ msg: ExtensionMessage; delayMs?: number }>,
) => {
  for (const { msg, delayMs } of seq) {
    if (delayMs) await new Promise((r) => setTimeout(r, delayMs));
    window.postMessage(msg, "*");
  }
};
