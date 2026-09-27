import { defineConfig, devices } from '@playwright/test';

// E2E-2 on Expo web: the critical journeys against the real API and PostgreSQL — nothing mocked.
// `pnpm e2e:stack` builds the API and exports this app pointed at it; DATABASE_URL must reach a
// migrated, seeded database (`pnpm verify` and CI provide a throwaway one).
const port = Number(process.env.E2E_MOBILE_PORT ?? 8082);
const apiPort = Number(process.env.E2E_API_PORT ?? 3100);

export default defineConfig({
  testDir: 'e2e/stack',
  reporter: [['list'], ['html', { open: 'never' }]],
  use: { baseURL: `http://localhost:${port}`, trace: 'retain-on-failure' },
  projects: [{ name: 'chromium', use: devices['Desktop Chrome'] }],
  webServer: [
    {
      command: 'node ../api/dist/main.js',
      url: `http://localhost:${apiPort}/health`,
      env: {
        PORT: String(apiPort),
        NODE_ENV: 'test',
        CORS_ALLOWED_ORIGINS: `http://localhost:${port}`,
        LOG_LEVEL: 'warn',
      },
    },
    {
      command: `pnpm exec expo serve --port ${port}`,
      url: `http://localhost:${port}`,
    },
  ],
});
