+++
id = "HARN-006"
epic = "HARN"
title = "Repeat only what the last red verify did not pass"
wave = 5
depends_on = ["HARN-005"]
touches = ["template/scripts/verify.sh", "template/.keelokit/bin/verify_tools.py", "template/docs/verify.md", "tests/test_verify_operativo.py"]
dimensions = ["dx"]
origin = "harbor:2026-11-01"
+++
## Context
A red step at minute 50 means rerunning the 50 green minutes. The history knows what passed.

Does NOT do: decide that a green step still holds after code changes in its packages (routing decides).

## User story
As whoever fixes a red, I want `pnpm verify --rerun-failed`, so that the rerun is the red step, what never ran, and what my fix calls for.

## Acceptance criteria
```gherkin
Scenario: [S1] The red step and what never ran are repeated
  Given a run red at build
  When pnpm verify --rerun-failed
  Then build and the later steps run; the earlier green ones don't

Scenario: [S2] Every red of a keep-going run is repeated
  Given a keep-going run red at lint and unit
  When --rerun-failed
  Then lint and unit run

Scenario: [S3] A new commit adds what its files call for
  Given a docs fix after the red
  When --rerun-failed
  Then format runs too; code changes mean the normal verify

Scenario: [S4] Without a red run it is the normal verify and says why
  Given no history, or a green last run
  When --rerun-failed
  Then the normal verify runs and says why

Scenario: [S5] A run is only narrowed at its own level
  Given a red --all run, or a red run without --all
  When --rerun-failed at the other level
  Then the normal verify, saying why

Scenario: [S6] A red run on a dirty tree is not narrowed
  Given a red run that saw uncommitted changes, since reverted
  When --rerun-failed
  Then the normal verify, saying why

Scenario: [S7] A step that ran twice and failed once is not passed
  Given e2e-stack green for web and red for mobile
  When --rerun-failed
  Then e2e-stack runs again

Scenario: [S8] A rerun that completes the red run seals the commit
  Given a red run, and a rerun (on the same commit, or after a fix routed to another step) that passes
  When together they passed every step of the diff's plan, on a clean tree, at the same base and level
  Then the seal is written at that level, and the history line has partial = false and composite_of

Scenario: [S9] No seal when coverage can't be proven
  Given a red --steps run, a package that came into scope later, or a dirty tree
  When the rerun passes
  Then no seal, and it says why
```

## Testable units
| Unit | Test type | File |
|---|---|---|
| verify.sh and verify_tools.py | integration (fixture repo, stub pnpm) | tests/test_verify_operativo.py |

## Definition of done
`scripts/verify.sh` green, every scenario covered by a test named `test_HARN_006_S<n>_…`,
`docs/verify.md` updated, `Story:` trailer on the completing commit.
