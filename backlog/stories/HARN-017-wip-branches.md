+++
id = "HARN-017"
epic = "HARN"
title = "Unfinished work moves between sessions on wip/ branches that never land"
wave = 16
depends_on = ["HARN-016"]
touches = ["template/.githooks/pre-push", "template/.keelokit/bin/verify_tools.py", "template/.keelokit/bin/doctor.py", "template/.keelokit/harness/rules.toml", "template/.keelokit/harness/agent-brief.md", "template/docs/verify.md", "skills/project-new/SKILL.md", "tests/test_verify_operativo.py", "tests/test_landing.py"]
dimensions = ["dx", "security"]
origin = "harbor:2026-11-02"
+++
## Context
A session cut off mid-work had no safe way to hand its work over: a red branch can't be pushed and --no-verify is forbidden. JOUNA solved it with wip/<topic> branches that run no verify and are refused on the way to main.

Does NOT do: land wip work. Whoever finishes it verifies it, or redoes it on a branch from origin/main.

## User story
As a session that must stop before its work is green, I want to hand it over on a wip/ branch, so that another session can finish it, and nothing unverified ever lands.

## Acceptance criteria
```gherkin
Scenario: [S1] A wip push runs no verify and says it cannot land
  Given [verify] wip_branches = "wip/" on origin/main
  When unfinished work is pushed to wip/topic
  Then nothing runs and the hook says it can't land

Scenario: [S2] A push holding wip work is refused, even after the branch is gone
  Given a wip tip origin/main lacks
  When a commit holding it is pushed to main or a branch, before or after the wip branch is deleted
  Then refused before any verify

Scenario: [S3] Wip work that passed a verify here no longer blocks
  Given the wip tip itself verified green and clean
  When it is pushed to main
  Then it goes through the usual verify

Scenario: [S4] Without the key a wip branch is an ordinary branch
  Given no wip_branches on origin/main (a local edit doesn't count)
  When a push to wip/topic
  Then verified like any branch

Scenario: [S5] The doctor checks the wip_branches key
  Given a value that isn't a branch-name prefix ending in /
  When doctor
  Then an ERROR naming the file
```

## Testable units
| Unit | Test type | File |
|---|---|---|
| the pre-push hook and verify_tools.py wip-* | integration (real pushes) | tests/test_verify_operativo.py |
| the doctor's check of the key | unit | tests/test_landing.py |

## Definition of done
`scripts/verify.sh` green, every scenario covered by a test named `test_HARN_017_S<n>_…`,
`Story:` trailer on the completing commit.
