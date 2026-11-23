import { mkdirSync, mkdtempSync, rmSync, writeFileSync } from 'node:fs';
import { tmpdir } from 'node:os';
import { dirname, join } from 'node:path';
import { fileURLToPath } from 'node:url';
import { afterEach, beforeEach, describe, expect, it } from 'vitest';
import { repoRoot, sleepsInSpecs, type Allow } from './_walk.js';

// stable-tests 3: never sleep to wait for work. A sleep long enough on your machine is too short on
// a loaded CI runner. Wait for the event, drain the queue, read once.
// A file that really needs one goes in ALLOW with its reason; a single line says why with
// `// arch-allow: <reason>`.
const ROOT = repoRoot(fileURLToPath(import.meta.url));
const ALLOW: Allow = {
  'apps/api/src/testing/race.spec.ts':
    'a deliberate one-millisecond yield that interleaves check-then-act code; it waits for no work',
};

describe('ARCH no sleeps in specs', () => {
  it('no spec waits with setTimeout, sleep or waitForTimeout', () => {
    const bad = sleepsInSpecs(ROOT, ALLOW);
    expect(bad, `sleeps found (wait for the event instead):\n${bad.join('\n')}`).toEqual([]);
  });
});

describe('no-sleeps-in-specs on fixtures', () => {
  let dir = '';
  const put = (rel: string, lines: string[]) => {
    mkdirSync(dirname(join(dir, rel)), { recursive: true });
    writeFileSync(join(dir, rel), lines.join('\n') + '\n');
  };
  beforeEach(() => {
    dir = mkdtempSync(join(tmpdir(), 'arch-sleeps-'));
    writeFileSync(join(dir, 'pnpm-workspace.yaml'), 'packages: []\n');
  });
  afterEach(() => rmSync(dir, { recursive: true, force: true }));

  it('FLEET-003.S4 a spec that sleeps to wait for work fails', () => {
    put('src/queue.test.ts', [
      "it('sends the email', async () => {",
      "  queue.push('welcome');",
      '  await new Promise((r) => setTimeout(r, 500));',
      '  expect(outbox).toHaveLength(1);',
      '});',
    ]);
    expect(sleepsInSpecs(dir)).toEqual(['src/queue.test.ts:3']);
  });

  it('FLEET-003.S4 a Playwright spec that waits a fixed time fails', () => {
    put('apps/web/e2e/save.spec.ts', [
      "test('saves', async ({ page }) => {",
      "  await page.getByRole('button', { name: 'Save' }).click();",
      '  await page.waitForTimeout(1000);',
      '});',
    ]);
    expect(sleepsInSpecs(dir)).toEqual(['apps/web/e2e/save.spec.ts:3']);
  });

  it('FLEET-003.S4 a spec that awaits the event itself passes', () => {
    put('src/queue.test.ts', [
      "it('sends the email', async () => {",
      "  const sent = once(outbox, 'sent');",
      "  queue.push('welcome');",
      '  await sent;',
      '  expect(outbox.items).toHaveLength(1);',
      '});',
    ]);
    expect(sleepsInSpecs(dir)).toEqual([]);
  });
});
