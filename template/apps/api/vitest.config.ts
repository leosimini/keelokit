import { defineConfig } from 'vitest/config';

// Unit tests: no database, no network.
export default defineConfig({
  test: { include: ['src/**/*.spec.ts'], exclude: ['src/**/*.integration.spec.ts'] },
});
