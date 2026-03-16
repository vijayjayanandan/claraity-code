/// <reference types="vite/client" />

// VS Code webview API — available at runtime inside VS Code webviews
declare function acquireVsCodeApi(): {
  postMessage(message: unknown): void;
  getState(): unknown;
  setState(state: unknown): void;
};

// CSS module imports
declare module "*.css" {
  const content: string;
  export default content;
}
