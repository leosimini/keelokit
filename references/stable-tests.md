# Tests that stay green

A test that fails only sometimes is a race: in the code, in the test, or in the clock. Find the cause. Never skip it, never retry it, never lengthen its timeout (FLAKY-1; the doctor fails when a timeout or `retries` grows). The spec-test writer reads this before writing tests; the reviewer checks a diff against it. Nine rules:

1. **Only your own data.** Filter every read to what the test created. No "a random window far away" and no "the first row".
2. **Global rows need a database of their own.** Cities, general rates, config: a helper with a lock and cleanup, or one database per worker. Two files sharing a global row will meet.
3. **Never sleep to wait for work.** Wait for the listener, drain the queue, read once. A sleep is a guess about a machine you don't control.
4. **Time comes from the code.** Inject the clock. Test it at local midnight, at the end of the month, across a daylight-saving change. `pnpm verify --all` reruns the unit tests a year ahead when libfaketime is installed; the nightly CI always does.
5. **Wait for the final shape of a screen,** not the first element that appears.
6. **Teardown wins.** What appears after the test ended must not reach the next one: cancel timers, close servers, await pending writes.
7. **Tools that run `git` start from a clean environment.** A hook sets `GIT_DIR` and friends; a test that inherits them can rewrite the real repository's config.
8. **A change of contract reaches every consumer in the same branch:** a shared field, a translation key, a payload. The merge of two green branches is where it breaks (the convoy's seam review looks there).
9. **Reproduce an intermittent red before fixing it.** More workers, a saturated CPU, the clock at the edge of a day: `.keelokit/bin/flaky.sh -n 20 --stress 4 --tz "UTC Pacific/Auckland" -- <test command>`. The reproduction stays as a test, and the guard goes in `docs/escapes.md` (`escapes.py add`).

A test that takes more than ~10 s alone is too heavy: make it cheaper instead of giving it more time. If a limit must be raised, measure the test alone and inside the full suite, and write both times in a comment next to it.

Arch-specs (`references/arch-specs/`) turn rules 3, 4 and 7 into tests that walk the source tree and fail on the forbidden pattern.
