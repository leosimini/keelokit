+++
id = "FLEET-002"
epic = "FLEET"
title = "The verify says how long it will take, as a range from its own history"
wave = 21
depends_on = ["FLEET-001"]
touches = ["template/scripts/verify.sh", "template/.keelokit/bin/verify_tools.py", "template/.keelokit/bin/status.py", "tests/test_verify_plan.py", "CHANGELOG.md"]
dimensions = ["logic", "dx"]
invariants = []
origin = "docs/fleet-lessons.md — coordination; JOUNA: long verifies always took longer than estimated"
+++
## Context
JOUNA's sessions promised times and missed them: every long verify took longer than estimated, and the
coordinator waited on hours that were guesses. `keelokit-verify.history` already keeps seconds per step
for every run on the machine. This story turns them into a range.

- `verify_tools.py plan` adds, for the planned steps, the median and the 90th percentile of each step's
  past durations on this machine with the same level (`changed` or `all`) and comparable workers, and
  prints the total as a range: "about 55–80 min (from 12 runs)". With fewer than 3 past runs it says it
  has no estimate yet.
- `status.py`, while a run goes, says the step it is on and the range left.
- The agent brief (FLEET-006) tells sessions to report ranges, never single times.

Does NOT do: estimate a machine with no history; promise anything to CI.

## User story
As a coordinator waiting on another session's verify, I want a range that comes from real runs, so that
I plan on facts and stop being surprised by every long run.

## Acceptance criteria
```gherkin
Scenario: [S1] A range from history
  Given 12 past runs of the same level on this machine
  Then the plan prints a range built from each step's median and 90th percentile, and the number of runs

Scenario: [S2] Too little history
  Given 2 past runs
  Then the plan says there is no estimate yet

Scenario: [S3] Different workers are not mixed
  Given past runs with 4 workers and a plan with 2 (FLEET-001)
  Then the estimate uses only comparable runs, or says it has none

Scenario: [S4] While running
  Then status.py shows the current step and the range left
```

## Testable units
| Unit | Test type | File |
|---|---|---|
| percentiles, comparability, the messages | unit, with a synthetic history | tests/test_verify_plan.py |

## Definition of done
`scripts/verify.sh` green, every scenario covered by a test titled with its id, a CHANGELOG line,
`Story: FLEET-002` trailer, addendum if the result differs.

## Addendum — 2026-11-24
What was built differs from the text above in these points (the smallest option consistent with the story):
- **`estimate`, not `plan`.** `verify_tools.py plan`'s output is the step list verify.sh reads, and it runs
  before the memory plan picks the workers. The range comes from a new `verify_tools.py estimate HISTORY --steps
  --level --workers`, called right after the memory plan; verify.sh prints it as `Estimate: about 55–80 min (from
  12 runs).` Not for a preflight (it stops long before the plan's end).
- **Which runs count.** Green, whole runs (not partial, `--packages`, narrowed, or a rerun that kept passes) of the
  same level, the newest 20. A red run stopped early and a partial one ran less than its plan, so their seconds
  would pull the range down. "This machine" is this clone's history (it lives in the git common dir).
- **Comparable workers.** The workers FLEET-001 planned must be equal for every worker step in this plan (`unit`,
  `integration`); none planned (the runner's default) is a kind of its own. Fewer than 3 comparable runs is "no
  estimate yet (N past runs like this one on this machine, M with other workers; it needs 3)".
- **What is summed.** Each planned step's median (low end) and 90th percentile (high end, linear interpolation),
  plus the setup steps the history has (`git`, `prisma`; `db` with integration). A planned step with no samples is
  named ("no history yet for e2e"). Low end rounded down, high end up.
- **Seconds per step id.** The history's `steps` were keyed by title; each line now also has `durations` (id →
  seconds, e2e-stack summed over apps). Lines written before are read through the titles, so the history the
  machine already has counts from the first run.
- **Range left.** The state file gains `step_id`, `step_since` and `estimate` (id:median:p90 per step in run order).
  `status.py` subtracts the time spent in the current step from its figures (none once past them), adds the later
  steps whole, and says nothing about time when a figure is missing or doesn't parse.
