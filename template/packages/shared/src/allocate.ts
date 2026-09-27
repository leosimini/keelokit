/**
 * Splits a whole amount — cents, seats, stock units — across weights so the parts always add up
 * to the total. Rounding each share on its own loses or invents units (3 × 33.33 ≠ 100.00); this
 * floors every share and hands the leftover units, one each, to the largest remainders (ties to
 * the earliest part). Use it wherever an amount is divided: fees, refunds, shared costs, quotas.
 *
 * The template's example of a critical rule (.keelokit/critical.toml): pure, so property tests
 * and mutation testing reach it. Delete it, and its area, if the product never divides amounts.
 */
export function allocate(total: number, weights: readonly number[]): number[] {
  if (!Number.isSafeInteger(total) || total < 0) {
    throw new RangeError(`allocate: total must be a whole, non-negative amount; got ${total}`);
  }
  if (weights.length === 0 || weights.some((w) => !Number.isFinite(w) || w < 0)) {
    throw new RangeError('allocate: weights must be a non-empty list of non-negative numbers');
  }
  const sum = weights.reduce((a, b) => a + b, 0);
  if (sum === 0) throw new RangeError('allocate: at least one weight must be positive');

  const exact = weights.map((w) => (total * w) / sum);
  const parts = exact.map(Math.floor);
  // Array.prototype.sort is stable, so equal remainders keep the parts' order.
  const byRemainder = exact
    .map((x, i) => ({ i, remainder: x - Math.floor(x) }))
    .sort((a, b) => b.remainder - a.remainder);
  let left = total - parts.reduce((a, b) => a + b, 0);
  for (let k = 0; left > 0; k = (k + 1) % byRemainder.length, left--) {
    parts[byRemainder[k].i] += 1;
  }
  return parts;
}
