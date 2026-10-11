import { existsSync } from 'node:fs';
import { defineConfig } from 'vitest/config';

// Against the real PostgreSQL in DATABASE_URL (CI sets it; locally apps/api/.env does).
if (existsSync('.env')) process.loadEnvFile('.env');

export default defineConfig({
  test: {
    // CI: per-test timings for the run summary's 10 slowest tests (.keelokit/bin/ci.py summary).
    reporters: process.env.CI ? ['default', 'json'] : ['default'],
    outputFile: { json: '../../ci-timings/integration-api.json' },
    include: ['src/**/*.integration.spec.ts'],
  },
});
