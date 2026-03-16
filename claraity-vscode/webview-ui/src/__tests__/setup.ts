/**
 * Vitest setup file.
 *
 * - Extends expect with jest-dom matchers (toBeInTheDocument, etc.)
 * - Mocks acquireVsCodeApi for the test environment
 */
import "@testing-library/jest-dom/vitest";

// Mock the VS Code webview API globally
const mockVSCodeApi = {
  postMessage: vi.fn(),
  getState: vi.fn(() => ({})),
  setState: vi.fn(),
};

globalThis.acquireVsCodeApi = () => mockVSCodeApi;
