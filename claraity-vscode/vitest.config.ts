import { defineConfig } from 'vitest/config';
import path from 'path';

export default defineConfig({
    test: {
        environment: 'node',
        globals: true,
        include: ['src/**/__tests__/**/*.test.ts'],
        alias: {
            vscode: path.resolve(__dirname, './__mocks__/vscode.js'),
        },
        clearMocks: true,
        restoreMocks: true,
        coverage: {
            include: ['src/**/*.ts'],
            exclude: ['src/**/__tests__/**'],
            reporter: ['text', 'text-summary'],
            reportsDirectory: 'coverage',
        },
    },
});
