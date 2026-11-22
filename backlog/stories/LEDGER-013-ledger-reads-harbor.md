+++
id = "LEDGER-013"
epic = "LEDGER"
title = "The ledger reads Harbor's logbook"
wave = 18
depends_on = ["LEDGER-012"]
touches = ["template/.keelokit/bin/ledger.py", ".keelokit/bin/ledger.py", "tests/test_ledger.py", "docs/design.md", "CHANGELOG.md"]
dimensions = ["logic", "integrity", "dx"]
invariants = ["INV-005"]
origin = "docs/ledger.md — Harbor and Swarm; Harbor's plan docs/ledger-phase6.md (HRB-2)"
+++
## Context
Harbor keeps what is under way in its logbook, the orphan branch `harbor/log` (TOML with a fixed schema,
written only by `harbor.py`). The ledger reads it, never writes it:

- a vessel sealed on its exact head in an open convoy (`harbor/convoys/<n>.toml`, `[[vessels]]`) →
  `delivered`, with its convoy and the convoy's state;
- an active worker with a `story` (`harbor/workers/…`, the key HRB-2 adds) → `in-progress`;
- a sailed convoy → the convoy of an `on-trunk` story (also from the `Convoy:` trailer HRB-1 adds), and
  `harbor/main.toml`'s moves give the exact arrival time;
- `show` adds the convoy's events.

`take`, when the project adopted Harbor (`git config harbor.py` set) and `harbor.py story take` exists,
calls it, so taking a story is a real lock (`STORY_TAKEN` reaches the session). Without Harbor, or with a
Harbor older than 0.6.0, nothing changes.

Blocked by HRB-2 (Harbor 0.6.0).

Does NOT do: write the logbook; fetch it (Harbor's hooks already do).

## User story
As a session in a project with Harbor, I want the ledger to include what Harbor knows, so that one command
tells me whether a story is delivered, in which convoy, and exactly when it reached the trunk.

## Acceptance criteria
```gherkin
Scenario: [S1] A sealed vessel in an open convoy
  Given a logbook with convoy 8 assembling and a vessel for AUTH-001 sealed on its head
  Then AUTH-001 is delivered, convoy 8

Scenario: [S2] A sailed convoy
  Given convoy 8 sailed and its merge commit carries `Convoy: 8`
  Then AUTH-001 is on-trunk with convoy 8 and the exact time from harbor/main.toml

Scenario: [S3] take with Harbor
  Given another active worker holds AUTH-002 in the logbook
  Then `ledger.py take AUTH-002` exits 1 with STORY_TAKEN naming that worker

Scenario: [S4] Without a logbook
  Given no harbor/log
  Then every state is as before LEDGER-013
```

## Testable units
| Unit | Test type | File |
|---|---|---|
| reading convoys, vessels, workers and moves from a test logbook; take delegating to a stub harbor.py | unit | tests/test_ledger.py |

## Definition of done
`scripts/verify.sh` green, every scenario covered by a test titled with its id, INV-005 cited, a CHANGELOG
line, `Story: LEDGER-013` trailer, addendum if the result differs.
