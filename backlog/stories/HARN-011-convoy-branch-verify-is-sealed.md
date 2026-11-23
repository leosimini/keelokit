+++
id = "HARN-011"
epic = "HARN"
title = "A convoy session verifies its branch with a sealed pnpm verify"
wave = 11
depends_on = ["HARN-010"]
touches = ["template/.keelokit/harness/agent-brief.md", "skills/build-story/SKILL.md", "template/docs/verify.md", "docs/design.md", "tests/test_landing.py", "tests/test_verify_operativo.py"]
dimensions = ["dx", "docs"]
origin = "harbor:2026-11-02"
+++
## Context
Under convoy the agent brief told a session to verify with `pnpm verify --since origin/main`, which never seals, so the pre-push hook ran the whole verify again when the branch was pushed. A plain `pnpm verify` compares with origin/main too, and seals.

Does NOT do: change --since (a branch agent comparing with another ref still gets no seal).

## User story
As a convoy session, I want the verify I run before delivering to count for the push, so that delivering a branch costs one verify, not two.

## Acceptance criteria
```gherkin
Scenario: [S1] A plain verify has the scope of --since origin/main
  Given a story branch
  When pnpm verify and pnpm verify --since origin/main run
  Then they run the same steps on the same packages

Scenario: [S2] The branch push doesn't run it again
  Given a green plain verify on the branch's final commit
  When the pre-push hook runs verify --use-seal
  Then nothing runs again; after a --since run it would
```

## Testable units
| Unit | Test type | File |
|---|---|---|
| verify.sh scope and seal | integration (fixture repo, stub pnpm) | tests/test_verify_operativo.py |
| the brief's convoy landing | unit (text) | tests/test_landing.py |

## Definition of done
`scripts/verify.sh` green, every scenario covered by a test named `test_HARN_011_S<n>_…`,
`Story:` trailer on the completing commit.
