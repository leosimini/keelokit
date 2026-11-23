/**
 * Fires `n` calls of `fn` at the same moment and returns every outcome, in call order. It is how a
 * test proves a `limit`, `once` or `transition` invariant (the Keelokit plugin's
 * references/invariants.md): book the last seat, send the reminder, confirm the payment — twenty
 * times at once — and assert how many succeeded and what the database holds afterwards.
 *
 * Every call waits at a barrier until all `n` have been created, so code that checks and then acts
 * in two round trips really interleaves. Use it against the real database (an
 * `*.integration.spec.ts` with `supertest` or the service itself), never against a mock: the race
 * lives in the transaction and the constraints, not in your code. Test-only; not part of the build.
 */
export async function race<T>(
  n: number,
  fn: (i: number) => Promise<T>,
): Promise<PromiseSettledResult<T>[]> {
  if (!Number.isInteger(n) || n < 2) throw new RangeError(`race: needs at least 2 calls; got ${n}`);
  let open!: () => void;
  const barrier = new Promise<void>((resolve) => (open = resolve));
  const calls = Array.from({ length: n }, async (_, i) => {
    await barrier;
    return fn(i);
  });
  open();
  return Promise.allSettled(calls);
}

/** The values of the calls that succeeded. */
export const fulfilled = <T>(results: PromiseSettledResult<T>[]): T[] =>
  results.flatMap((r) => (r.status === 'fulfilled' ? [r.value] : []));
