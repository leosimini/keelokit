# Escapes

Every bug that got past a story's own tests — caught by the reviewer, the breaker, the verifier,
a bug bash, or a user — and the check it left behind so its whole class can't come back. A fix
without a new check only repairs one case. `pnpm run doctor` fails on a row with an empty cell; when
nothing can catch the class automatically, write `none — <why>` and propose a review rule.

## Intermittent tests (FLAKY-1)

A test that sometimes fails is a race in the code or the test, not bad luck. Never lengthen its
timeout, retry it or skip it (the doctor fails when a timeout or `retries` grows); find the cause
(shared state, unawaited work, a clock, ordering) and fix it. Then add a row below: its date, the
cause, and the check that catches the whole class (a lint rule, a `race()` test, a fixed clock).
This log is the project's quality-gates file: one row per guard, each with its date and cause.

| Id | Date | Found by | What escaped | Class | Check added |
|---|---|---|---|---|---|
