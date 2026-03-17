/// <reference types="vitest/config" />
import { defineConfig } from "vite";
import react from "@vitejs/plugin-react-swc";

export default defineConfig({
  plugins: [react()],
  server: {
    port: 5173,
  },
  test: {
    environment: "jsdom",
    globals: true,
    setupFiles: ["src/__tests__/setup.ts"],
    exclude: ["e2e/**", "node_modules/**"],
  },
  build: {
    outDir: "dist",
    emptyOutDir: true,

    // Disable code splitting -- webviews cannot use dynamic import()
    rollupOptions: {
      input: "src/main.tsx",
      output: {
        entryFileNames: "webview.js",
        assetFileNames: "webview[extname]",
        manualChunks: undefined,
      },
    },

    // Inline assets < 100KB into the JS bundle
    assetsInlineLimit: 100_000,

    // VS Code 1.85+ ships Chromium ~120. Use es2022 for safe compatibility.
    target: "es2022",

    // Sourcemaps for debugging in Extension Dev Host
    sourcemap: true,

    // CSS extracted to webview.css (not inlined into JS)
    cssCodeSplit: false,

    minify: "esbuild",
  },
});
