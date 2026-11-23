import { mkdirSync, mkdtempSync, rmSync, writeFileSync } from 'node:fs';
import { tmpdir } from 'node:os';
import { dirname, join } from 'node:path';
import { fileURLToPath } from 'node:url';
import { afterEach, beforeEach, describe, expect, it } from 'vitest';
import { literalDates, repoRoot, type Allow } from './_walk.js';

// stable-tests 4: a calendar date written into a test passes today and fails the day it falls into
// the past (or out of the feature's window). Build dates from the injected clock: `addDays(now, 3)`.
// A file that really needs one goes in ALLOW with its reason; a single line says why with
// `// arch-allow: <reason>`.
const ROOT = repoRoot(fileURLToPath(import.meta.url));
const ALLOW: Allow = {
  // 'packages/billing/src/proration.test.ts': 'historic invoice dates, fixed by the product',
};

describe('ARCH no literal dates in specs', () => {
  it('no spec hard-codes a date from this decade', () => {
    const bad = literalDates(ROOT, ALLOW);
    expect(bad, `literal dates found (derive them from the clock):\n${bad.join('\n')}`).toEqual([]);
  });
});

describe('no-literal-dates on fixtures', () => {
  let dir = '';
  const put = (rel: string, lines: string[]) => {
    mkdirSync(dirname(join(dir, rel)), { recursive: true });
    writeFileSync(join(dir, rel), lines.join('\n') + '\n');
  };
  beforeEach(() => {
    dir = mkdtempSync(join(tmpdir(), 'arch-dates-'));
    writeFileSync(join(dir, 'pnpm-workspace.yaml'), 'packages: []\n');
  });
  afterEach(() => rmSync(dir, { recursive: true, force: true }));

  it('FLEET-003.S2 a spec with a hard-coded future date fails, naming the file and line', () => {
    put('src/billing.test.ts', [
      "import { expect, it } from 'vitest';",
      "it('is not due yet', () => {",
      "  const due = '2031-05-01T00:00:00Z';",
      '  expect(isDue(due)).toBe(false);',
      '});',
    ]);
    put('e2e/fixtures/plans.ts', ['export const renewal = new Date(2032, 0, 1);']);
    put('node_modules/lib/old.test.ts', ["const d = '2031-05-01';"]);
    expect(literalDates(dir).sort()).toEqual(['e2e/fixtures/plans.ts:1', 'src/billing.test.ts:3']);
  });

  it('FLEET-003.S2 a spec that derives the date from a clock passes', () => {
    put('src/billing.test.ts', [
      "import { expect, it } from 'vitest';",
      "it('is not due yet', () => {",
      '  const due = addDays(clock.now(), 3);',
      '  expect(isDue(due, clock)).toBe(false);',
      '});',
    ]);
    expect(literalDates(dir)).toEqual([]);
  });

  it('FLEET-003.S2 an allow-listed file or an arch-allow line passes', () => {
    put('src/history.test.ts', ["const launch = '2031-05-01';"]);
    put('src/report.test.ts', ["const fixed = '2031-05-01'; // arch-allow: the format under test"]);
    expect(literalDates(dir, { 'src/history.test.ts': 'historic dates' })).toEqual([]);
  });
});
