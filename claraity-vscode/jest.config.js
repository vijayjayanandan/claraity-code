/** @type {import('ts-jest').JestConfigWithTsJest} */
module.exports = {
    preset: 'ts-jest',
    testEnvironment: 'node',
    roots: ['<rootDir>/src'],
    testMatch: ['**/__tests__/**/*.test.ts'],
    moduleNameMapper: {
        // Mock the vscode module (not available outside VS Code)
        '^vscode$': '<rootDir>/__mocks__/vscode.js',
    },
    // Clear mocks between tests
    clearMocks: true,
    restoreMocks: true,
    // Coverage
    collectCoverageFrom: [
        'src/**/*.ts',
        '!src/**/__tests__/**',
    ],
    coverageDirectory: 'coverage',
    coverageReporters: ['text', 'text-summary'],
};
