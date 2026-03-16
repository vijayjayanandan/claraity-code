/**
 * React hook for VS Code webview <-> extension communication.
 *
 * acquireVsCodeApi() can only be called ONCE per webview session.
 * We call it at module scope and store the singleton.
 */
import { useCallback, useEffect, useRef } from "react";
import type { ExtensionMessage, WebViewMessage } from "../types";

// ── VS Code API singleton ──

interface VSCodeApi {
  postMessage(message: unknown): void;
  getState(): unknown;
  setState(state: unknown): void;
}

declare function acquireVsCodeApi(): VSCodeApi;

const vscodeApi: VSCodeApi =
  typeof acquireVsCodeApi === "function"
    ? acquireVsCodeApi()
    : {
        // Mock for running in a browser during development
        postMessage: (msg: unknown) =>
          console.log("[vscode mock] postMessage:", msg),
        getState: () => ({}),
        setState: (s: unknown) =>
          console.log("[vscode mock] setState:", s),
      };

// ── Hook ──

type MessageHandler = (message: ExtensionMessage) => void;

export function useVSCode(handler: MessageHandler) {
  const handlerRef = useRef<MessageHandler>(handler);
  handlerRef.current = handler;

  // Register message listener once
  useEffect(() => {
    const listener = (event: MessageEvent) => {
      const message = event.data as ExtensionMessage;
      handlerRef.current(message);
    };
    window.addEventListener("message", listener);
    return () => window.removeEventListener("message", listener);
  }, []);

  const postMessage = useCallback((message: WebViewMessage) => {
    vscodeApi.postMessage(message);
  }, []);

  const onReady = useCallback(() => {
    vscodeApi.postMessage({ type: "ready" });
  }, []);

  const getState = useCallback(<T,>(): T | undefined => {
    return vscodeApi.getState() as T | undefined;
  }, []);

  const setState = useCallback(<T,>(state: T): void => {
    vscodeApi.setState(state);
  }, []);

  return { postMessage, onReady, getState, setState };
}
