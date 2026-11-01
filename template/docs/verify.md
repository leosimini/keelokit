# `pnpm verify` — what it does, and how to trust it

The local gate decides; the CI audits (`docs/ci.md`). Rules: VER-1, CI-2, FMT-1, FLAKY-1.

| Command | When |
|---|---|
| `pnpm verify` | Before saying "done". Only the packages that changed since `origin/main`, and only the steps the change calls for |
| `pnpm verify --preflight` | Before a long run: tools, secret scan, format, lint, typecheck, doctor. Minutes, not an hour. Takes no lock |
| `pnpm verify --keep-going` | Do not stop at the first red: every independent step runs, and the reds are listed together at the end. Setup steps (database, client generation) still stop the run |
| `pnpm verify --all` | Everything, like the CI. Refuses to start on a loaded machine (`VERIFY_FORCE=1` overrides; `VERIFY_MAX_LOAD_FACTOR`, default 1.5 × cores) |
| `pnpm verify --since REF` | Compare with `REF` instead of `origin/main`: a branch agent runs only its part. Never sealed |
| `pnpm verify --use-seal` | What the pre-push hook runs: skip the run if this exact commit already passed, here or in a shared seal |
| `pnpm verify --steps unit,e2e-stack` | Only these steps (names below) and their setup. Never sealed |
| `pnpm verify --rerun-failed` | Only what the last red run did not pass, plus what files changed since then call for. Sealed when the two runs together cover the whole plan |
| `pnpm verify --packages ./apps/api,./packages/x` | These packages and their dependents instead of the changed ones (`--filter SELECTOR` goes to pnpm as is). Never sealed |

`--steps`, `--rerun-failed` and `--packages`/`--filter` combine with `--since`, `--all` and
`--keep-going` (`--steps` and `--rerun-failed` exclude each other and `--preflight`). They prove less
than a verify, so a seal never skips them and they write none — except the composite seal below;
they write the run state and the history as usual.

## Partial runs

**Step names** (`--steps`, the history): `secrets`, `format`, `lint`, `typecheck`, `doctor`, `unit`,
`integration`, `build`, `e2e`, `e2e-stack`, `mutation`, `sast`, `audit`, `clock` — the routing's steps,
the secret scan, the doctor and the date-bomb rerun (`clock` runs only with `--all`). An unknown name stops the run with exit 2 before anything runs. A named
step brings its setup: the up-to-date check, the Prisma client and the throwaway database.

**`--rerun-failed`** reads `keelokit-verify.history`. The last run of this commit or an ancestor decides:
if it was red, started on a clean tree, and had the same base (`origin/main`, or `--since`), the same
`--packages`/`--filter` and the same level (`--all` or not), the run is the steps it planned and did not pass (the red ones and the ones
a first red never reached) plus what the files changed since its commit call for. A new commit also
reruns `secrets`, `doctor` and `clock`, which the routing doesn't decide: gitleaks scans the new commits
and the doctor reads the whole repo.

**The composite seal.** When a narrowed rerun passes on a clean tree without `--since`, `--packages` or
`--filter`, and the steps it ran plus the passes it kept from the red run are every step of this diff's
plan, on packages the red run covered, it writes the seal at the red run's level and records the line
with `partial = false` and `composite_of` = the red run's head (the seal file gets `composite_of=` too).
A chain of reruns works the same way. When it can't prove that (a red `--steps` run planned less, a
package came into scope after the red run, a dirty tree), it says which and doesn't seal. Otherwise — no
history, a green last run, a red in a setup step, a run that saw uncommitted changes, a file no route
knows, every step needed — it says
why and runs the normal verify (which seals when green). Unknown goes up, never down.

**`--packages`** takes package folders (each must have a `package.json`) and runs them and their
dependents with the steps the changed files call for; `--filter` passes a pnpm selector as is and
must select at least one package.

## The history

`keelokit-verify.history` has one JSON line per run: `head` (the full sha), `base`, `level`, `result`,
`rc`, `partial`, `clean` (the tree at the start), `composite_of` (the red run a composite seal builds
on, else null), `inherited` (passes a rerun kept), `proven_packages` (where every pass counted holds),
`scope` (the `--packages`/`--filter` selectors), `steps` (name and seconds), `failed`
(step titles), `planned` / `passed` / `failed_steps` (step names), `packages` (the folders pnpm put in
scope, `.` for the root) and `step_packages` (only the steps whose packages differ from the run's:
`lint` runs at the root, `integration` on `apps/api`, `e2e-stack` on each app it walked), and the
known `causes` of a red. A tool can tell from it whether a green step still holds after a fix: the
fix's files and the packages the step covered.

## Shared seals

A seal lives in the clone that ran the verify, so a push from another machine runs it again. With
`[verify] shared_seals = "origin/harbor/log:harbor/seals/{head}.toml"` in `.keelokit/state.toml`,
`--use-seal` also fetches that branch and reads the TOML file for this commit (`{head}` is the full
sha), written by whoever verified it (Harbor does):

```toml
head = "<full sha>"
base = "<origin/main's sha when it passed>"
exit = 0
level = "changed"   # or "all"
```

It is accepted only when `head` is this exact commit, `base` is `origin/main` now, `exit` is 0, the
level covers the request (`all` for `--all`), the tree is clean and the partial-run flags are absent;
otherwise verify says which condition failed and runs. `KEELOKIT_NO_SEAL=1` turns it off. **Trusting
that branch is trusting everyone who can push to it**: whoever can write a file there can let a commit
skip the local gate, so protect it like `main`. The doctor checks the key's shape.

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
