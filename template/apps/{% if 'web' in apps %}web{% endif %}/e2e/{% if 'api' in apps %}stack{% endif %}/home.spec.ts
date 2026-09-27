// Enforces house rule E2E-2: a critical journey against the real API and database. No
// page.route() here (lint stops it); the hermetic e2e/ specs cover the states a real API can't
// be made to show on demand, like "the API is down".
import { expect, test } from '@playwright/test';
import en from '../../src/i18n/en.json' with { type: 'json' };

test.use({ locale: 'en-US' });

test('WEB-HOME.S1 the home page reports the real API and database as healthy', async ({ page }) => {
  await page.goto('/');

  await expect(page.getByRole('status')).toHaveText(en['health.ok']);
});
