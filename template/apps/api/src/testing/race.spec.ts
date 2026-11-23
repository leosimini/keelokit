import { describe, expect, it } from 'vitest';
import { fulfilled, race } from './race.js';

// A database round trip between the check and the act — where every overbooking bug lives.
const roundTrip = () => new Promise((resolve) => setTimeout(resolve, 1));

describe('race', () => {
  it('interleaves check-then-act code, so a limit guarded that way breaks', async () => {
    let booked = 0;
    const bookLastSeat = async () => {
      const seen = booked; // check…
      await roundTrip();
      if (seen >= 1) throw new Error('full');
      booked = seen + 1; // …then act, on a stale read
    };

    const results = await race(5, bookLastSeat);

    // All five callers saw a free seat: the bug a sequential test never shows.
    expect(fulfilled(results)).toHaveLength(5);
  });

  it('holds the limit when checking and taking are one step', async () => {
    let booked = 0;
    const bookLastSeat = async (i: number) => {
      await roundTrip();
      if (booked >= 1) throw new Error('full'); // like UPDATE … WHERE booked < capacity
      booked += 1;
      return i;
    };

    const results = await race(5, bookLastSeat);

    expect(fulfilled(results)).toHaveLength(1);
    expect(results.filter((r) => r.status === 'rejected')).toHaveLength(4);
    expect(booked).toBe(1);
  });

  it('returns one outcome per call, in call order', async () => {
    const results = await race(3, async (i) => i * 10);
    expect(results).toEqual([
      { status: 'fulfilled', value: 0 },
      { status: 'fulfilled', value: 10 },
      { status: 'fulfilled', value: 20 },
    ]);
  });

  it('needs at least two calls to race', async () => {
    await expect(race(1, async () => 1)).rejects.toThrow(RangeError);
  });
});
