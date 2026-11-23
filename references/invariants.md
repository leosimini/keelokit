# Invariants: the rules that must always hold, and the tests that prove it

A scenario says what happens in one case. An invariant says what must hold in every case, for
every user, at every moment, even when two requests arrive together. Most P0 bugs are a broken
invariant that no scenario described: money that doesn't add up, a notice sent twice, a limit
passed by two taps at once.

Invariants are one catalogue with four uses, like `dimensions.md`:

- **intake** writes them in `docs/context/domain.md`, one line each, with an id and a class:
  ```markdown
  - [INV-001] [MUST] Charged = refunded + held + fee, for every payment — class: conservation (S2)
  - [INV-002] [MUST] A reminder goes out at most once per booking — class: once (S1)
  - [INV-003] [MUST] A slot never holds more bookings than its capacity — class: limit (S1)
  ```
- **backlog** lists the invariants a story must keep (`invariants = ["INV-003"]`) and gives the
  story the `integrity` dimension;
- **build** has the verifier write the test the class calls for, before any code, and the
  breaker attack it;
- **check-bugbash** runs an `integrity` lens that attacks every invariant on the running app.

`python3 .keelokit/bin/doctor.py` checks that every invariant has a known class, that stories only name invariants
that exist, and that every invariant of a done story is cited by an active test title (INV-1).
It can't check that the test is the right kind; the verifier and the reviewer do.

Invariants are about the product, so they're the same whatever the stack. The examples below are
TypeScript, but the tests they describe are the same in any language.

## The classes

| Class | What must hold | Typical cases | The test that proves it |
|---|---|---|---|
| `conservation` | Totals add up: nothing is lost or invented | Money (charged = refunded + held + fee), stock, seats, points, balances, splits | **Property test** over generated inputs, plus a reconciliation query after the concurrency test |
| `once` | A side effect happens at most (or exactly) once | Notices, emails, pushes, charges, webhooks, payouts, cron jobs on two instances | **Replay test**: the same request, event or job twice, and twice at once; count the effects |
| `limit` | A bound holds under concurrency | Capacity, quotas, stock ≥ 0, one active X per Y, unique slugs, rate limits | **Concurrency test**: N simultaneous attempts against the real database; exactly the allowed number succeed |
| `transition` | Only allowed state changes happen | Order: paid → shipped, never cancelled → shipped; one confirmation per booking | **Transition table**: every (state, action) pair, including the forbidden ones, and two transitions racing |
| `isolation` | A subject sees and changes only what is theirs | Tenants, owners, roles, shared devices after logout | **Matrix test**: every route × role, including a stranger and another tenant (AUTHZ-1) |
| `time` | Deadlines and windows are right in the user's time zone | "24 h before", cut-off times, expiry, DST, end of month | **Clock test** with a fixed clock at the edges: just before, at, just after, across DST |
| `consistency` | Two representations agree | What the screen shows = what is charged; copy = behaviour; cache = source; a derived total = recomputed | **Cross-check test**: compute both sides from the same input and compare; for copy, a test of the promised behaviour (COPY-1) |

Choosing a class: ask how it breaks. Numbers stop adding up → `conservation`. Something happens
twice → `once`. Too many of something → `limit`. Something happens that shouldn't be possible at
all → `transition`. The wrong person → `isolation`. The right thing at the wrong moment →
`time`. Two places disagree → `consistency`. If it breaks in two ways, write two invariants.

## How to hold each class (where the fix goes)

Tests find the bug; the design decides whether it can happen at all. Keep the rule in one place
every caller goes through.

- **conservation**: amounts in integer minor units (cents), never floats. Divide amounts with
  one function that hands out the remainder (the template ships `allocate()` in
  `packages/shared` as the example). Write the parts of a movement in one transaction.
- **once**: an idempotency key with a unique constraint, written *before* the side effect,
  in the same transaction as the state change (an outbox). Retries, double clicks, redelivered
  webhooks and two cron instances then collide on the constraint instead of sending twice.
- **limit**: make checking and taking one step: `UPDATE … SET taken = taken + 1 WHERE id = $1
  AND taken < capacity` and look at the row count, or a unique constraint, or `SELECT … FOR
  UPDATE` in a transaction. "Read the count, then insert" is the bug, however fast it looks.
- **transition**: one function per entity decides allowed transitions, from a table; the
  update carries the expected state (`WHERE status = 'pending'`) so a concurrent change loses.
- **isolation**: every query scoped by the owner or tenant from the session, never from the
  request body; the route's access decision in `authz.matrix.ts`.
- **time**: store instants in UTC, compute in the user's zone with `Intl`/a tz library, inject
  the clock so tests can fix it.
- **consistency**: one source of truth and derived values computed from it, never copied; the
  screen asks the server for the number the server will charge.

## The tests, concretely

### conservation: a property test (fast-check, in the template)

```ts
import fc from 'fast-check';

const cents = fc.integer({ min: 0, max: 10_000_00 });
const percent = fc.integer({ min: 0, max: 100 });

it('INV-001 a refund never makes charged ≠ refunded + held + fee', () => {
  fc.assert(
    fc.property(cents, percent, (amount, pct) => {
      const m = settle(amount, pct); // the pure rule
      return m.charged === m.refunded + m.held + m.fee;
    }),
  );
});
```

Put the rule in a pure function so a property test and mutation testing (MUT-1) can reach it;
the API only wraps it in a transaction.

### limit: a concurrency test on the real database (`race()`, in the template)

```ts
import { fulfilled, race } from '../testing/race.js';

it('INV-003 twenty people booking the last seat at once get one booking', async () => {
  const slot = await seedSlot({ capacity: 1 });
  const results = await race(20, (i) =>
    request(app.getHttpServer()).post(`/slots/${slot.id}/bookings`).set(auth(user(i))),
  );
  expect(fulfilled(results).filter((r) => r.status === 201)).toHaveLength(1);
  expect(await prisma.booking.count({ where: { slotId: slot.id } })).toBe(1);
});
```

It lives in an `*.integration.spec.ts` (real PostgreSQL). A mock can't show this bug: the race
lives in the transaction and the constraints. Assert on the response codes *and* on what the
database holds afterwards.

### once: a replay test

```ts
it('INV-002 a reminder job run twice, even at the same time, sends one reminder', async () => {
  const booking = await seedBooking({ startsAt: inHours(23) });
  await race(2, () => runReminderJob(clockAt(now)));
  await runReminderJob(clockAt(now)); // and once more, later
  expect(sentNotices.for(booking.id)).toHaveLength(1);
});
```

Send side effects through a port (a `Notifier` interface) so the test counts what was sent; the
real adapter is covered by one integration test of its own.

### transition: the table, forbidden rows included

```ts
it.each([
  ['pending', 'confirm', 'confirmed'],
  ['confirmed', 'cancel', 'cancelled'],
  ['cancelled', 'confirm', 'rejected'], // forbidden
])('INV-004 %s + %s → %s', async (from, action, expected) => { … });
```

Then race two transitions from the same state and check only one wins.

### time: a fixed clock at the edges

Test just before, at and just after every boundary, in a zone other than UTC, and on a DST
change date of the product's markets.

## What the breaker does with them

For every invariant the story keeps, the breaker (`agents/breaker.md`) tries to break it on the
branch. It uses the attack for the class: generated inputs for `conservation`, replays and
double submits for `once`, N parallel requests for `limit`, forbidden and racing transitions,
another tenant for `isolation`, the edges of every window for `time`, and screen against server
for `consistency`. An attack that works becomes a failing test (written by the verifier), then a
fix, then a row in `docs/escapes.md`.
