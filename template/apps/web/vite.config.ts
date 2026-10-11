import react from '@vitejs/plugin-react';
import { defineConfig } from 'vitest/config';

export default defineConfig({
  plugins: [react()],
  // e2e/ belongs to Playwright.
  test: {
    environment: 'happy-dom',
    include: ['src/**/*.test.{ts,tsx}'],
    // CI: per-test timings for the run summary's 10 slowest tests (.keelokit/bin/ci.py summary).
    reporters: process.env.CI ? ['default', 'json'] : ['default'],
    outputFile: { json: '../../ci-timings/unit-web.json' },
  },
});
