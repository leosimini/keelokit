+++
id = "HARN-005"
epic = "HARN"
title = "Run only the verify steps you name"
wave = 4
depends_on = []
touches = ["template/scripts/verify.sh", "template/.keelokit/bin/verify_tools.py", "template/docs/verify.md", "tests/test_verify_operativo.py"]
dimensions = ["dx"]
origin = "harbor:2026-11-01"
+++
## Context
Harbor reruns one step of a convoy (`e2e-stack` after a fix) without the hour of the rest. Today
the plan comes only from the routing.

Does NOT do: name packages (HARN-007).

## User story
As whoever lands a convoy, I want `pnpm verify --steps unit,e2e-stack`, so that a rerun costs only those steps.

## Acceptance criteria
```gherkin
Scenario: [S1] Only the named steps run
  Given a change that calls for every step
  When pnpm verify --steps unit
  Then only the unit tests run (plus setup)

Scenario: [S2] An unknown name is an error before anything runs
  Given any change
  When pnpm verify --steps unit,e2e-stak
  Then exit 2 naming e2e-stak, nothing runs

Scenario: [S3] Never sealed, but state and history are written
  Given a green --steps run
  When it ends
  Then no seal; the history line has partial = true and the planned steps

Scenario: [S4] Combines with --since, --all and --keep-going
  Given --steps with each
  When it runs
  Then the scope and the keep-going behaviour are those of the other flag
```

## Testable units
| Unit | Test type | File |
|---|---|---|
| verify.sh and verify_tools.py | integration (fixture repo, stub pnpm) | tests/test_verify_operativo.py |

## Definition of done
`scripts/verify.sh` green, every scenario covered by a test named `test_HARN_005_S<n>_…`,
`docs/verify.md` updated, `Story:` trailer on the completing commit.
