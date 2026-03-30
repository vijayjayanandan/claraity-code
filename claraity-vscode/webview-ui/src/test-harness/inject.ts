/**
 * Global helpers for injecting messages into the webview from
 * Playwright tests or the browser console.
 *
 * Exposes:
 *   window.__claraityInject(msg)          — inject a single ExtensionMessage
 *   window.__claraityInjectSequence(seq)  — inject a sequence with optional delays
 */
import type { ExtensionMessage } from "../types";

declare global {
  interface Window {
    __claraityInject: (msg: ExtensionMessage) => void;
    __claraityInjectSequence: (
      seq: Array<{ msg: ExtensionMessage; delayMs?: number }>,
    ) => Promise<void>;
  }
}

window.__claraityInject = (msg: ExtensionMessage) => {
  window.postMessage(msg, "*");
};

window.__claraityInjectSequence = async (
  seq: Array<{ msg: ExtensionMessage; delayMs?: number }>,
) => {
  for (const { msg, delayMs } of seq) {
    if (delayMs) await new Promise((r) => setTimeout(r, delayMs));
    window.postMessage(msg, "*");
  }
};
