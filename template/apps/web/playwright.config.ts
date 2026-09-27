import { defineConfig, devices } from '@playwright/test';

// Overridable so parallel worktrees can run e2e at the same time.
const port = Number(process.env.E2E_PORT ?? 4173);

export default defineConfig({
  testDir: 'e2e',
  // e2e/stack/ runs against the real API instead (playwright.stack.config.ts, `pnpm e2e:stack`).
  testIgnore: 'stack/**',
  reporter: [['list'], ['html', { open: 'never' }]],
  use: { baseURL: `http://localhost:${port}`, trace: 'retain-on-failure' },
  projects: [{ name: 'chromium', use: devices['Desktop Chrome'] }],
  // Serves the production build (`pnpm e2e` builds first), not the dev server.
  webServer: {
    command: `pnpm exec vite preview --port ${port} --strictPort`,
    url: `http://localhost:${port}`,
  },
});
