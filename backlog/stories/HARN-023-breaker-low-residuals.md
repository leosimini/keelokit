+++
id = "HARN-023"
epic = "HARN"
title = "HARN-022's low residuals: a Decision after a squash, and str.splitlines on trailers and story bodies"
wave = 27
depends_on = ["HARN-022"]
touches = ["template/.keelokit/bin/ledger.py", ".keelokit/bin/ledger.py", "tests/test_breaker.py", "tests/test_ledger_swarm.py", "docs/ledger.md", "docs/escapes.md", "CHANGELOG.md", "backlog/stories/HARN-023-breaker-low-residuals.md"]
dimensions = ["logic", "dx"]
invariants = []
risky = true
+++
## Context
HARN-022's cold breaker rounds 6 and 7 left LOW findings, which the coordinator asked to keep out of HARN-022 (2026-11-28):

- A person's `Decision` after a squash landing (the remedy `BREAKER_UNRESOLVED` offers) turns the squash's warnings
  into `BREAKER_STALE`: the decided round's head names no commit here, so it reaches nothing. Probe:
  /tmp/breaker7-HARN-022/probe_squash_decision.py (round 7).
- `parse_trailers` splits git's `%(trailers:only,unfold)` with `str.splitlines`, so a trailer value holding U+2028
  forges a second trailer git does not see (a `Swarm-Task`, a `Dropped`, a `Convoy`, a No-story category); show lists
  a forged swarm task. `breaker_record` splits the story body the same way. Probe:
  /tmp/breaker7-HARN-022/probe_trailer_sep.py (round 7).

Does NOT do: anything HARN-022's open HIGH and MEDIUM findings need (they are HARN-022's, by the coordinator's call).

## User story
As the person who decides at the cap, I want my Decision to resolve a squash-landed story and no line separator to
forge a trailer, so that the remedy the ledger offers works and what git reads is what the ledger reads.

## Acceptance criteria
```gherkin
Scenario: [S1] A Decision after a squash landing resolves it
  Given a risky story whose rounds were recorded on a branch that was squash-landed
  When a decider's Decision line follows its last round
  Then check reports no BREAKER_STALE for it (the BAD_ENTRY warning stays)

Scenario: [S2] Line separators never forge a trailer
  Given a commit whose trailer value holds U+2028, U+2029 or U+0085
  Then the ledger reads exactly the trailers git reads, and a story body is split at newlines only
```

## Testable units
| Unit | Test type | File |
|---|---|---|
| a Decision after a squash | integration (real git) | tests/test_breaker.py |
| trailers and story bodies split at newlines only | integration (real git) | tests/test_ledger_swarm.py |

## Definition of done
`scripts/verify.sh` green, every scenario covered by a test titled with its id, the two ledger.py copies identical,
`Story: HARN-023` on the completing commit, its breaker rounds recorded below.
