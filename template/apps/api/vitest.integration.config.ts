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
    // One database for every file: files run one at a time, so two specs never see each other's rows
    // (a per-worker database copy is the step after this, when the suite gets long).
    fileParallelism: false,
  },
});
