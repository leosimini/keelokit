import { defineConfig, devices } from '@playwright/test';

// E2E-2: the critical journeys against the real API and PostgreSQL — nothing mocked. `pnpm
// e2e:stack` builds the API and this app (pointed at it); DATABASE_URL must reach a migrated,
// seeded database (`pnpm verify` and CI provide a throwaway one). Ports are overridable so
// parallel worktrees don't collide.
const port = Number(process.env.E2E_PORT ?? 4173);
const apiPort = Number(process.env.E2E_API_PORT ?? 3100);

export default defineConfig({
  testDir: 'e2e/stack',
  reporter: [['list'], ['html', { open: 'never' }]],
  use: { baseURL: `http://localhost:${port}`, trace: 'retain-on-failure' },
  projects: [{ name: 'chromium', use: devices['Desktop Chrome'] }],
  webServer: [
    {
      // The API exactly as it deploys (the build output), on its own port.
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
      command: `pnpm exec vite preview --port ${port} --strictPort`,
      url: `http://localhost:${port}`,
    },
  ],
});
