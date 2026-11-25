+++
id = "LEDGER-014"
epic = "LEDGER"
title = "The ledger sees the swarm's deliveries"
wave = 19
depends_on = ["LEDGER-013"]
touches = ["template/.keelokit/bin/ledger.py", ".keelokit/bin/ledger.py", "tests/test_ledger.py", "tests/test_ledger_swarm.py", "docs/design.md", "docs/ledger.md", "docs/escapes.md", "scripts/unit_shard.py", "CHANGELOG.md"]
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

Scenario: [S4] Swarm data is data
  Given swarm branches and commits with hostile content (huge or invalid-UTF-8 messages, control characters,
    odd task ids, wrong trailers, a malformed snapshot list)
  Then no command crashes, and check's differences and exit code are those without them

Scenario: [S5] A delivery never attributes on its own
  Given a trunk commit with `Swarm-Task:` and no story trailer, brought by no merge with one
  Then it is UNATTRIBUTED, and check --rules-ref <rev> gives the same differences with or without swarm data

Scenario: [S6] The phase gate: a convoy carrying swarm deliveries lands
  Given a Harbor logbook, swarm branches and trunk commits where convoy 12 sailed two swarm deliveries of AUTH-008
  Then show AUTH-008 (text and --json) says each piece's story, who made it and which convoy sailed it
```

## Testable units
| Unit | Test type | File |
|---|---|---|
| swarm branches, the swarm list in --json, show, hostile data, the gate | unit, local remote | tests/test_ledger_swarm.py |

## Definition of done
`scripts/verify.sh` green, every scenario covered by a test titled with its id, a CHANGELOG line, `Story:
LEDGER-014` trailer, addendum if the result differs. With HRB-1..3 and SWM-1..3 done, the gate of phase 3
(docs/ledger.md, "Plan") opens Keelokit 0.17.0 and Harbor 0.6.0.

## Addendum — 2026-11-25
Built against the schema this story describes (swarm/<task> branches, `Part-of:` and `Swarm-Task:` trailers): the
session could not read leosimini/enjambre-dev. What differs from the story as written:
- Scenarios S4 (hostile Swarm data), S5 (a delivery never attributes on its own; `--rules-ref` unchanged) and S6 (the
  phase gate: show says each piece's story, author and convoy) were added; tests in tests/test_ledger_swarm.py.
- A delivery's `Swarm-Task:` must be its branch's task (`swarm/<task>`), with exactly one task id per commit; merges are
  no deliveries. Each entry also names the Harbor convoy that carries it (open, sealed on the branch's head) or sailed
  it, and a delivery a revert undid is `reverted`.
- `Part-of:` alone on a `swarm/*` branch still makes the story in-progress (LEDGER-003's rule for any branch); it is
  only not listed as a swarm delivery.
- `--json` gained `swarm: {error}`; `show --json`'s commits gained `author` and `swarm_task` (additive, schema 1).

## Breaker rounds
- Round 1 · head afd3ebbd4c6d95c0beb9043cbaa8cf7bfc31477d · 2 findings: ESC-346, ESC-347 · fixed in a325316 (tests), c0954f1
- Round 2 · head 3af523dd551070b0057eaf68f2c682a3cef39e6d · 1 finding: ESC-348 · fixed in 71a665c (tests), 6da5df2
- Round 3 · head a33642209292a30446aadb229b654c8d078be4c2 · 1 finding: ESC-349 · fixed in 60febc5 (tests), 5f4f295
  The cap (3) is reached with round 3's finding fixed but not re-attacked: a person's Decision is needed (another round,
  or land as it is).
