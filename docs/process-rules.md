# Process rules: what, why, how to check

Lessons from long, parallel use of Keelokit on a real monorepo. Each is a house rule in
`template/.keelokit/harness/rules.toml` with a check; the details a project reads are in its
`docs/ci.md`, `.keelokit/harness/agent-brief.md` and `docs/prelaunch-debt-ledger.md`.

| Rule | What | Why | How it is checked |
|---|---|---|---|
| **CI-1** time budget | Jobs split by kind of test, each with its own `timeout-minutes`; never raise a timeout, a test timeout or retries; split or shard | One job with one timeout fails as *cancelled* when its steps grow, and nobody reads cancelled | Doctor: a job without timeout warns, a raised one fails (against main). `ci-report` job: time per job, warning above 2/3, 10 slowest tests |
| **Health** | A cancelled run is not a green one; show how many runs main is without a green | Cancelled runs hid a broken main for days | `ci.py health` (alarm on a red head or 2+ runs without a green), run nightly and by `status.py` |
| **CI-2** local gate | `pnpm verify` runs what the CI runs, routed by the diff (docs only: seconds), `--all` for everything; the CI runs nightly and by hand; pre-push runs verify, never `--no-verify` | Billed minutes found what a local run finds in seconds | `.keelokit/verify-map.toml`: the doctor fails on a CI job it lacks or a step `verify.sh` lacks; `tests/test_doctor.py` |
| **Starting the CI** | Nightly `schedule`, `ci.py dispatch` with an Actions-write token; a 403 is the token's permission; read the failing job and step, not the service containers' logs | Runs waited for a person; a database's expected errors were mistaken for the cause | `docs/ci.md`; `ci.py jobs` |
| **SESS-1** sessions | One session = one finished, pushed job; the shared brief; reports ≤ 8 lines with paths; the coordinator verifies hashes on `origin/main`; a ten-line status; rounds every 15 min | "Done" sessions whose work never reached main; rules repeated in prompts drifted | `status.py` (branches not on main, verify lock); the verify lock itself |
| **MIG-1** migrations | Stories that add migrations go one per wave; a new migration sorts after main's last | Parallel migrations applied out of order | Doctor (`check_migrations`, `check_migration_waves`) |
| **FLAKY-1** intermittent tests | Find the race; never a longer timeout, a retry or a skip; log date, cause and check in `docs/escapes.md` | Retries made races rarer, never gone | Doctor (timeouts and `retries` that grew), the guard (QA-4), ESC-1 |
| **FMT-1** format | Format before every commit; `format:check` fails on a diff; line endings pinned; on a rebase that conflicts only on formatting, keep your content and reformat | A formatter that differed between laptop and CI reformatted 56 files | `ci:checks`, `verify.sh`, doctor (`.gitattributes` `eol=lf`) |
| **Risk process** | Tests by a different agent than the builder, adversarial review, depth by risk | A builder grading its own work | Already `build-story` (trivial / light / full), VERIFY-2, REVIEW-1 |
| **DEBT-1** zero debt | Every finding fixed or decided with a recommendation, never "known issue"; "Needs the owner" lists what only the owner can supply | Parked findings piled up for the launch week | Doctor and `doctor --launch` on `docs/prelaunch-debt-ledger.md` |

## Added after 0.10.0

| Rule | What | Why | How it is checked |
|---|---|---|---|
| **VER-1** trustworthy verify | A required tool missing fails; a killed run exits non-zero and leaves its state; the exit code decides; only the exact green commit is skipped (the seal); `--keep-going`, `--preflight`, known causes, a busy machine refused | One red per hour-long run, a missing scanner that let two fake tokens through, a run cut by memory that nobody noticed | `tests/test_verify_operativo.py` (state, seal, keep-going, preflight, signals, load, `--since`, routing); `status.py` shows CUT |
| **Routing** | Each change runs the steps it needs; unknown files run everything; `--all` is every step | A docs change paid for the whole suite | `tests/test_verify_plan.py` walks the template's files |
| **RISK-1** tier floor | `risk.toml` gives the lowest build tier for a change's files; unknown is full; the agent goes up, never down | Judgement alone let dangerous changes ride as light | `doctor --tier`; `tests/test_risk_and_review.py` |
| **Rounds and formats** | Two review rounds; the reviewer's and the agents' reports have a fixed shape | Rounds without end, reports nobody could count | `review.py` |
| **Escape → guard** | An escaped bug is logged only with a guard of its whole class, or an exception with an owner | A fix of one case let the class return | `escapes.py add` (refuses otherwise) |
| **Stable tests** | Nine rules, arch-specs that walk the tree, `flaky.sh` to reproduce | A "sometimes red" test is a race | `references/stable-tests.md`, `references/arch-specs/`, FLAKY-1 |
| **COORD-1** watch and convoys | One captain on watch with an expiring check-in, a logbook branch, convoys that sail when `ready` passes, handoff to relieve a stale captain, an hourly check that revives the role | The coordinating session was the only holder of the plan | `tests/test_coord.py` (race between two claimants, expiry, handoff, ready, seam, budget) |
