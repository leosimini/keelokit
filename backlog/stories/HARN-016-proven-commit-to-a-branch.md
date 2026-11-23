+++
id = "HARN-016"
epic = "HARN"
title = "A commit that already passed can reach a branch from another checkout"
wave = 15
depends_on = ["HARN-015"]
touches = ["template/.githooks/pre-push", "template/.keelokit/bin/verify_tools.py", "template/docs/verify.md", "tests/test_verify_operativo.py"]
dimensions = ["dx", "security"]
origin = "harbor:2026-11-02"
+++
## Context
0.12 refuses every push of a commit that isn't checked out, because the verify vouches only for HEAD. A session that verified its branch and switched away had to switch back to push it. The verify history already records which commits passed a clean, full run against which main.

Does NOT do: anything for main, master or release, which keep refusing.

## User story
As a session handing over a verified branch, I want to push it without checking it out again, so that a proven commit isn't verified twice, and an unproven one still can't get through.

## Acceptance criteria
```gherkin
Scenario: [S1] A proven commit reaches a branch from another checkout
  Given a commit with a clean, full green verify here against origin/main
  When it is pushed to its branch while another is checked out
  Then it goes through and nothing runs

Scenario: [S2] Never to main and never without proof
  Given the same commit to main, a commit with no green run, or one that passed only with --since
  When it is pushed
  Then refused

Scenario: [S3] A moved main voids the proof
  Given origin/main moved after the green run
  When the commit is pushed to its branch
  Then refused
```

## Testable units
| Unit | Test type | File |
|---|---|---|
| the pre-push hook and verify_tools.py proven | integration (real pushes, real verify.sh) | tests/test_verify_operativo.py |

## Definition of done
`scripts/verify.sh` green, every scenario covered by a test named `test_HARN_016_S<n>_…`,
`Story:` trailer on the completing commit.
