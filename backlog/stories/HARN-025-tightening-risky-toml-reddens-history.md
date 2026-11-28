+++
id = "HARN-025"
epic = "HARN"
title = "Tightening risky.toml never turns landed history into errors"
wave = 29
depends_on = ["HARN-022"]
touches = ["template/.keelokit/bin/ledger.py", ".keelokit/bin/ledger.py", "tests/test_breaker.py", "docs/ledger.md", "docs/escapes.md", "CHANGELOG.md", "backlog/stories/HARN-025-tightening-risky-toml-reddens-history.md"]
dimensions = ["logic", "dx"]
invariants = []
risky = true
+++
## Context
HARN-022's cold breaker, round 20, found it; it predates HARN-022 (HARN-021). The trunk judges all history after the
rule's start by the current risky.toml, so adding a path (the documented, product-owned flow) turns commits that
already landed into errors: RISKY_NO_STORY on old `No-story:` commits, RISKY_AFTER_CLOSE on a closed story's past
`Part-of:` commits, BREAKER_MISSING for a story closed while it was not risky. Past `No-story:` commits cannot get
rounds, so there is no remedy, and the pull request that tightens the rule passes. Probe:
/tmp/breaker20-HARN-022/probes/p4_tighten_rules.py.

Direction (the coordinator's): judge each commit by the risky.toml in force when it was made (its first reachable
version), or judge history only from the rule change.

Does NOT do: loosen what a rule change itself is (a change to risky.toml stays a risky change).

## User story
As the person who owns the product's risky paths, I want to add a path without turning the trunk red, so that the
rule grows with the product and still judges every change made under it.

## Acceptance criteria
```gherkin
Scenario: [S1] Adding a risky path judges what comes after it
  Given a trunk with landed history and a risky.toml
  When a story adds a path to risky.toml with a clean round
  Then commits that landed before the change are judged by the rules in force then, and later ones by the new rules
```

## Testable units
| Unit | Test type | File |
|---|---|---|
| a tightened rule and the history before it | integration (real git) | tests/test_breaker.py |

## Definition of done
`scripts/verify.sh` green, every scenario covered by a test titled with its id, the two ledger.py copies identical,
`Story: HARN-025` on the completing commit, its breaker rounds recorded below.
