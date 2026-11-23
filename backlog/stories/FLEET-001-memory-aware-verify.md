+++
id = "FLEET-001"
epic = "FLEET"
title = "The verify fits its test workers to the memory the machine has, and records what each step used"
wave = 20
depends_on = []
touches = ["template/scripts/verify.sh", "template/.keelokit/bin/verify_tools.py", "template/.keelokit/bin/status.py", "tests/test_verify.py", "tests/test_verify_plan.py", "docs/design.md", "CHANGELOG.md", "docs/escapes.md", "template/.keelokit/bin/run-local.sh", "tests/test_run_local.py"]
dimensions = ["logic", "nfr", "dx"]
invariants = []
origin = "docs/fleet-lessons.md — lesson 1; JOUNA 2026-11-22: ~15 h lost, runs killed by memory (T39 x3, credentials x2, UXC-121 x4)"
+++
## Context
JOUNA lost about 15 hours in one night to the kernel killing test runs for memory: each integration
shard built its own related-test map (~4.6 GB), three shards did not fit, and everything fell back to
one or two shards at 2–2.5 h a piece. Keelokit today names a memory kill after it happens
(`verify_tools.py` causes `heap` and `killed`) and refuses a full run on a busy machine (load average,
another test run), but it never checks memory before starting and never chooses the number of workers.

This story prevents the kill instead of explaining it:
- **Record.** Each step's peak memory goes into `keelokit-verify.history` (`peak_mb` per step): the
  cgroup's `memory.peak` when the step runs in its own cgroup v2 scope, else the maximum resident size of
  the step's process tree (`/usr/bin/time -f %M` when present), else absent.
- **Plan.** Before a run, `verify_tools.py plan` reads the memory available (`MemAvailable`, or the
  cgroup's `memory.max` minus `memory.current`, whichever is lower) and, for every step with a recorded
  peak per worker, sets its workers to `min(cores, floor(available × 0.8 / peak_per_worker))`, at least 1.
  The test runners take it through their own flags (`--maxWorkers`, `--pool-options`, shards).
  `[verify] memory_per_worker_mb` overrides the measure.
- **Refuse early.** When even one worker of a step needs more than is available, the preflight stops in
  seconds with the numbers, instead of an hour-long run ending in a kill.
- **Say it.** The plan line and `status.py` show the workers chosen and why
  ("integration: 2 workers, 5.1 GB free, 2.3 GB each last time").

Does NOT do: change how a project shards its tests (JOUNA's shared related map is JOUNA's); retry a killed
run; lower workers below 1.

## User story
As a session that runs a long verify on a cloud container or a laptop, I want the verify to start only
with as many workers as fit in memory, so that a run is never killed halfway and mistaken for a bug.

## Acceptance criteria
```gherkin
Scenario: [S1] Peaks are recorded
  When a verify runs a step
  Then its history line has that step's peak memory when the machine can measure it, and omits it when it can't

Scenario: [S2] Workers fit the memory
  Given 6 GB available and an integration step that peaked at 2.3 GB per worker on 8 cores
  Then the plan runs it with 2 workers and says so

Scenario: [S3] Nothing fits: stop in seconds
  Given 1.5 GB available and a step that needs 2.3 GB for one worker
  Then the preflight stops before running anything, with both numbers, and exit 3 like a busy machine

Scenario: [S4] No measure: as today
  Given no recorded peak and no override
  Then the step runs with today's workers

Scenario: [S5] The override wins
  Given [verify] memory_per_worker_mb = 1500
  Then the plan uses it instead of the measure

Scenario: [S6] A cgroup limit counts
  Given a container whose cgroup memory.max is lower than the host's MemAvailable
  Then the plan uses the cgroup's figure
```

## Testable units
| Unit | Test type | File |
|---|---|---|
| peak recording, the workers formula, cgroup vs MemAvailable, the override | unit, with a fake /proc and cgroup tree | tests/test_verify_plan.py |
| the preflight refusal and the plan line | unit | tests/test_verify.py |

## Definition of done
`scripts/verify.sh` green, every scenario covered by a test titled with its id, `docs/design.md` mentions
the memory plan, a CHANGELOG line, `Story: FLEET-001` trailer, addendum if the result differs.

## Addendum — 2026-11-23
What was built differs from the text above in these points (decided while building, found by the review,
the breaker and the verifier):
- **Which steps.** Workers are planned and refused only for `unit` (and the date-bomb `clock` rerun, which
  takes unit's number) and `integration` (only when `apps/api` exists). The e2e scripts build in the same
  command (`vite build`, `expo export`, the API build), so their peak is the build's, not a Playwright
  worker's: e2e and e2e-stack peaks are recorded, never planned or refused on.
- **The figure.** `peak_mb` per step comes from the step's own child cgroup v2 (`memory.peak`) where the
  verify's cgroup allows one, else from the largest process of the step's tree (`wait4`'s maximum resident
  size, the same figure as `/usr/bin/time -f %M`, without needing that binary). The per-worker figure is the
  most seen in the last 10 runs that measured the step, so a narrowed rerun or a small `--packages` run
  can't erase the real peak. Non-finite or absurd figures (over 1 TB) are skipped.
- **Free memory.** A cgroup v2 limit adds back the cgroup's reclaimable cache (`inactive_file`); cgroup v1
  limits are not read.
- **Only when memory is the limit.** A step whose workers would be `cores` anyway keeps today's command and
  says nothing, so a measured peak never adds flags on a machine with room.
- **Per machine.** A planned unit step also runs its packages one at a time (`--workspace-concurrency=1`),
  or pnpm's four packages at once would multiply the workers by four.
- **A refusal is not a red run.** Exit 3 leaves no history line, like a busy machine. `VERIFY_FORCE=1` runs
  the step with 1 worker.
- **Also fixed while landing:** `run-local.sh`'s native build watcher could miss its TERM and poll for
  2000 × 5 s (a test hung 90 s in a pre-push run); it now stops by a stop file within one round.
