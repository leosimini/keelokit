import { defineConfig, devices } from '@playwright/test';

// E2E-1 on Expo web: the static export renders the same React tree as the native app.
// Overridable so parallel worktrees can run e2e at the same time.
const port = Number(process.env.E2E_MOBILE_PORT ?? 8082);

export default defineConfig({
  testDir: 'e2e',
  reporter: [['list'], ['html', { open: 'never' }]],
  use: { baseURL: `http://localhost:${port}`, trace: 'retain-on-failure' },
  projects: [{ name: 'chromium', use: devices['Desktop Chrome'] }],
  // Serves the export (`pnpm e2e` builds it first), not the dev server.
  webServer: {
    command: `pnpm exec expo serve --port ${port}`,
    url: `http://localhost:${port}`,
  },
});
