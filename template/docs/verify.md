# `pnpm verify` — what it does, and how to trust it

The local gate decides; the CI audits (`docs/ci.md`). Rules: VER-1, CI-2, FMT-1, FLAKY-1.

| Command | When |
|---|---|
| `pnpm verify` | Before saying "done". Only the packages that changed since `origin/main`, and only the steps the change calls for |
| `pnpm verify --preflight` | Before a long run: tools, secret scan, format, lint, typecheck, doctor. Minutes, not an hour. Takes no lock |
| `pnpm verify --keep-going` | Do not stop at the first red: every independent step runs, and the reds are listed together at the end. Setup steps (database, client generation) still stop the run |
| `pnpm verify --all` | Everything, like the CI. Refuses to start on a loaded machine (`VERIFY_FORCE=1` overrides; `VERIFY_MAX_LOAD_FACTOR`, default 1.5 × cores) |
| `pnpm verify --since REF` | Compare with `REF` instead of `origin/main`: a branch agent runs only its part. Never sealed |
| `pnpm verify --use-seal` | What the pre-push hook runs: skip the run if this exact commit already passed |

## Landing policy

`[landing] policy` in `.keelokit/state.toml` (absent = `direct`). `direct`: a session runs
`pnpm verify` and pushes main; the pre-push hook is the last gate. `convoy`: a session never pushes
main; it pushes its branch with `pnpm verify --since origin/main` green on that exact hash, and
Harbor (`/harbor:*`) verifies the convoy branch once before it lands. The pre-push hook stays the
template's gate for main; with `convoy` the doctor notes that the per-branch gate is Harbor's.

## What a change calls for (routing)

`.keelokit/verify-routing.toml` maps files to steps: each file takes the first route that matches it,
and a change runs the union. A docs-only change runs the format check, the secret scan and the
doctor: seconds. Three guards keep the map honest: **a file no route knows runs everything**,
**`--all` is every step**, and `tests/test_verify_plan.py` in Keelokit walks the template's files.
When verify says "N changed files match no route", add a route for that kind of file.

## The seal

A green run writes `head`, the base it passed against, the level (`changed` or `all`) and the date in
the git directory (`keelokit-verify.seal`) if the working tree was clean. The pre-push hook calls
`verify --use-seal` and skips the repeat only when the commit, the base and the clean tree are all the
same, and the seal's level covers the request. A new commit, a rebase that moved the base or any
edit means the run happens again. This replaces the habit of `git push --no-verify` after a green
run: the guard still blocks `--no-verify` in agent sessions. `KEELOKIT_NO_SEAL=1` turns it off.

## When it fails

- The exit code is the result. A verify killed by a signal exits 143/130/129 and says at which step.
- After a red, the log is scanned for known causes (`.keelokit/red-causes.toml` plus the built-in
  ones: memory, disk, the database starting, formatting, secrets, lockfile, migrations, time zones,
  kills) and prints "look here first".
- `keelokit-verify.state` in the git directory says `running`, `pass` or `fail`, the step and the pid:
  `python3 .keelokit/bin/status.py` shows `verify: CUT` when a run died without finishing.
- Time per step is printed at the end and kept in `keelokit-verify.history` (one JSON line per run: result, steps, failed steps, causes).

## Tools the CI uses must exist here

A missing `gitleaks` or `semgrep` fails the run (exit 4) instead of printing a note. To skip one on
purpose: `KEELOKIT_ALLOW_MISSING="semgrep" pnpm verify`.

## Date bombs

With libfaketime installed, `--all` reruns the unit tests with the clock a year ahead
(`FAKETIME_DONT_FAKE_MONOTONIC=1 faketime -f '+365d' …`); the nightly CI does it always. A test that
passes today and fails next year is found before it turns main red with no code change.
