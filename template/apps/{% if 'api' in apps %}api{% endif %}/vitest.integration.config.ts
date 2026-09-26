import { existsSync } from 'node:fs';
import { defineConfig } from 'vitest/config';

// Against the real PostgreSQL in DATABASE_URL (CI sets it; locally apps/api/.env does).
if (existsSync('.env')) process.loadEnvFile('.env');

export default defineConfig({
  test: { include: ['src/**/*.integration.spec.ts'] },
});
