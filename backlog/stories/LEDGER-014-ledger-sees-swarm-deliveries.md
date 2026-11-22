+++
id = "LEDGER-014"
epic = "LEDGER"
title = "The ledger sees the swarm's deliveries"
wave = 19
depends_on = ["LEDGER-013"]
touches = ["template/.keelokit/bin/ledger.py", ".keelokit/bin/ledger.py", "tests/test_ledger.py", "docs/design.md", "CHANGELOG.md"]
dimensions = ["logic", "dx"]
invariants = []
origin = "docs/ledger.md — Harbor and Swarm; Swarm's plan docs/ledger-refs.md (SWM-2)"
+++
## Context
A swarm helper delivers a branch `swarm/<task-id>` in the code repo; after SWM-2 its commits carry
`Part-of: <ID>` and `Swarm-Task: <id>` (written by the helper's prompt or by the runner). The ledger never
reads the swarm repo (another repo, other credentials, more network in every hook); it reads those
branches and trailers in the code repo:

- an unintegrated `swarm/*` branch with `Part-of: <ID>` → the story is `in-progress`, and `--json`'s
  `swarm` list has the task id, the branch and the head;
- once integrated (by a merge, which attributes it if the helper's trailers were missing), `show` lists
  each task with its `Swarm-Task:` id and its author;
- a `swarm/*` branch without those trailers is not counted.

Blocked by SWM-2 (Swarm).

Does NOT do: read the swarm repo; know who lent the capacity beyond the commit's author.

## User story
As a session that integrates work the swarm did, I want the ledger to show which pieces of a story came
from the swarm and who made them, so that nobody asks or redoes them.

## Acceptance criteria
```gherkin
Scenario: [S1] A delivery not yet integrated
  Given origin swarm/t-20261201-ab12 with a commit `Part-of: AUTH-008` and `Swarm-Task: t-20261201-ab12`
  Then AUTH-008 is in-progress and show lists that delivery under in progress

Scenario: [S2] An integrated delivery
  Given that branch merged into the trunk
  Then show lists task t-20261201-ab12 with its author among AUTH-008's commits

Scenario: [S3] A swarm branch without trailers
  Then it is not counted for any story
```

## Testable units
| Unit | Test type | File |
|---|---|---|
| swarm branches, the swarm list in --json, show | unit, local remote | tests/test_ledger.py |

## Definition of done
`scripts/verify.sh` green, every scenario covered by a test titled with its id, a CHANGELOG line, `Story:
LEDGER-014` trailer, addendum if the result differs. With HRB-1..3 and SWM-1..3 done, the gate of phase 3
(docs/ledger.md, "Plan") opens Keelokit 0.17.0 and Harbor 0.6.0.
