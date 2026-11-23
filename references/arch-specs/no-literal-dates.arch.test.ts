import { mkdirSync, mkdtempSync, rmSync, symlinkSync, writeFileSync } from 'node:fs';
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

  it('FLEET-003.S2 Date.UTC with a year of this era fails; a line that pins the clock passes', () => {
    put('src/renewal.test.ts', [
      'const due = new Date(Date.UTC(2031, 0, 1));',
      "vi.setSystemTime(new Date('2026-03-29T00:30:00Z'));",
      "await page.clock.install({ time: new Date('2031-05-01T08:00:00') });",
      "await page.clock.setFixedTime('2031-05-01T10:00:00');",
    ]);
    expect(literalDates(dir)).toEqual(['src/renewal.test.ts:1']);
  });

  it('FLEET-003.S2 helper folders are scanned, and the JSON fixtures in them', () => {
    const date = ["export const due = '2031-05-01';"];
    for (const helper of ['testing', 'test-utils', '__mocks__', 'mocks', '__fixtures__']) {
      put(`src/${helper}/data.ts`, date);
    }
    put('e2e/fixtures/plans.json', ['{ "renewal": "2031-05-01" }']);
    expect(literalDates(dir).sort()).toEqual([
      'e2e/fixtures/plans.json:1',
      'src/__fixtures__/data.ts:1',
      'src/__mocks__/data.ts:1',
      'src/mocks/data.ts:1',
      'src/test-utils/data.ts:1',
      'src/testing/data.ts:1',
    ]);
  });

  it('FLEET-003.S2 the walker skips hidden and tmp folders and never follows a symlink', () => {
    const date = ["const due = '2031-05-01';"];
    put('src/a.test.ts', date);
    put('.claude/worktrees/x/src/a.test.ts', date);
    put('tmp/a.test.ts', date);
    put('packages/web/tmp/a.test.ts', date);
    const outside = mkdtempSync(join(tmpdir(), 'arch-outside-'));
    try {
      writeFileSync(join(outside, 'b.test.ts'), date[0] + '\n');
      symlinkSync(outside, join(dir, 'src/linked'));
      symlinkSync(join(dir, 'missing.test.ts'), join(dir, 'src/dangling.test.ts'));
      symlinkSync('.', join(dir, 'src/loop'));
      expect(literalDates(dir)).toEqual(['src/a.test.ts:1']);
    } finally {
      rmSync(outside, { recursive: true, force: true });
    }
  });
});
