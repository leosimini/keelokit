+++
id = "FLEET-006"
epic = "FLEET"
title = "The agent brief takes the fleet's lessons: push before waiting, wait on state, ranges, archive, never --no-verify"
wave = 25
depends_on = ["LEDGER-008", "FLEET-002"]
touches = ["template/.keelokit/harness/agent-brief.md", "skills/coordinate/SKILL.md", "skills/build-story/SKILL.md", "tests/test_process.py", "CHANGELOG.md"]
dimensions = ["dx", "docs"]
invariants = []
origin = "docs/fleet-lessons.md — lesson 8 and coordination"
+++
## Context
Five habits JOUNA paid for in one night, each cheap to write down where every parallel session reads:

- **Push before any long wait.** An idle cloud session can lose its container, its verify and its unpushed
  work (two runs lost). Before a wait longer than a few minutes, push: the story's branch when it is
  verified, else `wip/<topic>` with the same commits (WIP-1), never commits that exist only on `wip/`.
- **Wait on state, never on a log line.** Three sessions went silent waiting for the wrong text; one lost
  50 minutes with its verify already green. The brief's "Waiting" section today lists "a log line" among
  the conditions to wait on; it goes, replaced by the verify's state (`status.py`, the exit code), a CI
  run's state, or a remote ref.
- **Ranges, not hours.** Report how long a run will take as the range FLEET-002 prints.
- **Archive when delivered.** A cloud session archives itself once its work is pushed and reported, so the
  list shows only what is alive.
- **Every delegated prompt says: never `--no-verify`.** Subagents tried it twice; the guard blocked it, and
  saying it up front saves the round.

`coordinate` and `build-story` say the same where they start sessions and agents.

Depends on LEDGER-008 because both edit the agent brief, and on FLEET-002 for the ranges.

Does NOT do: change the guard (it already blocks `--no-verify`, prefixes included).

## User story
As a session working in parallel with many others, I want the brief to carry the habits that cost the
fleet hours, so that I don't pay for them again.

## Acceptance criteria
```gherkin
Scenario: [S1] Push before waiting
  Then the agent brief says to push before any wait longer than a few minutes, and how (branch or wip/ with the same commits)

Scenario: [S2] No log-line waits
  Then the brief's Waiting section no longer lists a log line, and names the verify's state, CI state and remote refs

Scenario: [S3] Ranges, archive, --no-verify
  Then the brief asks for ranges, archiving on delivery, and every delegated prompt to forbid --no-verify

Scenario: [S4] The skills repeat it
  Then coordinate and build-story carry the same lines where they start sessions and agents
```

## Testable units
| Unit | Test type | File |
|---|---|---|
| the brief's and skills' text | unit | tests/test_process.py |

## Definition of done
`scripts/verify.sh` green, every scenario covered by a test titled with its id, a CHANGELOG line,
`Story: FLEET-006` trailer, addendum if the result differs.
