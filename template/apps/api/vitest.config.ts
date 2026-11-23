import { defineConfig } from 'vitest/config';

// Unit tests: no database, no network.
export default defineConfig({
  test: {
    // CI: per-test timings for the run summary's 10 slowest tests (.keelokit/bin/ci.py summary).
    reporters: process.env.CI ? ['default', 'json'] : ['default'],
    outputFile: { json: '../../ci-timings/unit-api.json' },
    include: ['src/**/*.spec.ts'],
    exclude: ['src/**/*.integration.spec.ts'],
  },
});
