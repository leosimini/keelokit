# CI — budget, health and how to start it

The local gate decides; the CI audits. `pnpm verify` runs what the CI runs (its map is
`.keelokit/verify-map.toml`); the CI runs on every push and pull request, **every night** and **by
hand**. Rules: CI-1, CI-2 (`.keelokit/harness/rules.toml`). The doctor checks them.

## 1. A time budget per job (CI-1)

| Why | A job with one `timeout-minutes` breaks silently when the sum of its steps grows: GitHub reports **cancelled**, not failed, and nobody reads a cancelled run. |
|---|---|
| Rule | Jobs are split by kind of test, each with its own `timeout-minutes`: cheap checks (`checks`), unit, UI/mobile journeys (`e2e`, `e2e-stack`), integration with the database (`integration`). **Never raise a timeout** (or a test's timeout or retries) to make a job pass: split the job or shard it. |
| Check | The `ci-report` job writes each job's time and share of its budget, and the 10 slowest tests, into the run summary, and warns above 2/3. Locally: `python3 .keelokit/bin/ci.py budget [RUN_ID]`. The doctor fails when a timeout grows against main, or a job has none. |

To shard a slow Playwright job: a matrix `shard: [1, 2, 3]` and `playwright test --shard=${{ matrix.shard }}/3`;
to split by app, one job per app calling `pnpm --filter ./apps/<app> e2e`. Give each its own timeout
and add it to `.keelokit/verify-map.toml`.

## 2. Cancelled is not green (health)

`python3 .keelokit/bin/ci.py health` counts the runs of `main` since its last green one. A failure or
timeout at the head, or **two or more runs in a row without a green** (cancelled included), is an
alarm (exit 1). The nightly run prints it in its summary; `.keelokit/bin/status.py` shows it with
the rest. A run cancelled by a newer push is normal once; several in a row means a job hits its
timeout (look at `ci.py budget`).

## 3. One command, same as the CI (CI-2)

`pnpm verify` routes by what changed since `origin/main` (docs only: seconds), `--all` runs
everything. The pre-push hook runs it; **never `--no-verify`**. When you add a CI job, add it to
`.keelokit/verify-map.toml` in the same commit: the doctor fails on a job the map lacks or a step
`scripts/verify.sh` lacks. To make the CI audit-only (nightly + by hand), delete the `pull_request`
and `push` triggers from `.github/workflows/ci.yml`.

## 4. Starting the CI without a person

- **The nightly trigger** (`schedule`) is already in the workflow. It needs nobody.
- **By hand or from a script**: `python3 .keelokit/bin/ci.py dispatch` (or Actions > CI > *Run
  workflow*), with a fine-grained token in `$GITHUB_TOKEN` that has **Actions: read and write** on
  the repository (and Workflows if a script edits workflow files).
- **A 403** from an integration's token means that token has no `actions` permission; it is not a
  CI failure. Use the nightly trigger, a token as above, or run `pnpm verify --all` locally: the
  same gate.

## 5. Reading a failed run

`python3 .keelokit/bin/ci.py jobs [RUN_ID]` prints which job and which step failed, was cancelled
or timed out. Read that step's log. **Do not conclude from the service containers' logs** (the
`postgres` container logs expected errors while it starts and when tests probe constraints): they
are noise next to the step that actually failed.
