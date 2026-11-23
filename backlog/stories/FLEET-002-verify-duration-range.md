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
