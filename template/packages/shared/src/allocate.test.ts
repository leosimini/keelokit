import fc from 'fast-check';
import { describe, expect, it } from 'vitest';
import { allocate } from './allocate.js';

// A conservation invariant proven for thousands of generated inputs, not three hand-picked ones:
// a property test. In a product, the title cites the invariant's id from docs/context/domain.md
// (e.g. 'INV-001 a split conserves the total') — `pnpm run doctor` checks it once the story is done.
const amount = fc.integer({ min: 0, max: 1_000_000_000_00 });
const weights = fc
  .array(fc.integer({ min: 0, max: 1_000 }), { minLength: 1, maxLength: 12 })
  .filter((w) => w.some((x) => x > 0));
const sum = (xs: number[]) => xs.reduce((a, b) => a + b, 0);

describe('allocate', () => {
  it('conserves the total for any amount and weights (class: conservation)', () => {
    fc.assert(fc.property(amount, weights, (total, w) => sum(allocate(total, w)) === total));
  });

  it('gives each part its exact share, within one unit', () => {
    fc.assert(
      fc.property(amount, weights, (total, w) =>
        allocate(total, w).every((part, i) => Math.abs(part - (total * w[i]) / sum(w)) < 1),
      ),
    );
  });

  it('gives nothing to a zero weight', () => {
    fc.assert(fc.property(amount, weights, (total, w) => allocate(total, [...w, 0]).at(-1) === 0));
  });

  it('hands leftover units to the largest remainders, ties to the earliest part', () => {
    expect(allocate(100, [1, 1, 1])).toEqual([34, 33, 33]);
    expect(allocate(5, [2, 1])).toEqual([3, 2]);
    expect(allocate(7, [1, 1, 1, 1, 1])).toEqual([2, 2, 1, 1, 1]);
    expect(allocate(10, [3, 3, 4])).toEqual([3, 3, 4]);
    expect(allocate(0, [1, 1])).toEqual([0, 0]);
  });

  it('refuses amounts it cannot split in whole units', () => {
    for (const total of [10.5, -1, Number.MAX_SAFE_INTEGER + 1]) {
      expect(() => allocate(total, [1])).toThrow(/total must be a whole, non-negative amount/);
    }
  });

  it('refuses weights that are missing, negative or not numbers', () => {
    for (const w of [[], [2, -1], [1, Number.NaN], [1, Number.POSITIVE_INFINITY]]) {
      expect(() => allocate(10, w)).toThrow(/weights must be a non-empty list/);
    }
    expect(() => allocate(10, [0, 0])).toThrow(/at least one weight must be positive/);
  });
});
