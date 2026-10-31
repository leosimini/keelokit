import { describe, expect, it } from 'vitest';
import { offenders } from './_walk';

// stable-tests 4: a calendar date written into a test passes today and fails the day it falls into the
// past (or the feature's window). Build dates from the injected clock: `addDays(now, 3)`.
const ROOT = new URL('../..', import.meta.url).pathname; // adjust
const ALLOW: Record<string, string> = {
  // 'src/billing/proration.test.ts': 'historic invoice dates, fixed by the product',
};

describe('ARCH no literal dates in specs', () => {
  it('no spec hard-codes a date from this decade', () => {
    const bad = offenders(ROOT, /\.(test|spec)\.[cm]?[jt]sx?$/, /['"`]20[2-3]\d-\d{2}-\d{2}|new Date\(\s*20[2-3]\d\s*,/, ALLOW);
    expect(bad, `literal dates found (derive them from the clock):\n${bad.join('\n')}`).toEqual([]);
  });
});
