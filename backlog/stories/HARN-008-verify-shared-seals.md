+++
id = "HARN-008"
epic = "HARN"
title = "Accept a seal another machine pushed to git"
wave = 7
depends_on = ["HARN-007"]
touches = ["template/scripts/verify.sh", "template/.keelokit/bin/verify_tools.py", "template/docs/verify.md", "tests/test_verify_operativo.py", "template/.keelokit/bin/doctor.py", "skills/project-new/SKILL.md", "tests/test_landing.py"]
dimensions = ["dx", "security"]
origin = "harbor:2026-11-01"
+++
## Context
The seal is per clone: a push from a machine that didn't verify runs the whole verify again.
Harbor verifies a convoy once and pushes it from wherever it is.

Does NOT do: sign seals. Trusting the branch is trusting who can push to it (documented).

## User story
As whoever pushes a convoy verified elsewhere, I want `--use-seal` to accept a seal in git, so that the same commit isn't verified twice.

## Acceptance criteria
```gherkin
Scenario: [S1] A seal from another machine skips the run
  Given [verify] shared_seals and a matching seal on that branch
  When pnpm verify --use-seal
  Then nothing runs, and it says whose trust that is

Scenario: [S2] Every condition is checked and a refusal says why
  Given a seal with another head, base, exit or a level that doesn't cover --all
  When --use-seal
  Then the run happens and says which condition failed

Scenario: [S3] A dirty tree, a missing seal or no-seal flags run
  Given any of them
  When --use-seal
  Then the run happens

Scenario: [S4] Without the key nothing changes
  Given no [verify]
  When --use-seal
  Then no shared-seal message

Scenario: [S5] The doctor checks the key's shape
  Given a malformed shared_seals
  When doctor
  Then an ERROR naming the file
```

## Testable units
| Unit | Test type | File |
|---|---|---|
| verify.sh and verify_tools.py | integration (fixture repo, stub pnpm) | tests/test_verify_operativo.py, tests/test_landing.py |

## Definition of done
`scripts/verify.sh` green, every scenario covered by a test named `test_HARN_008_S<n>_…`,
`docs/verify.md` updated, `Story:` trailer on the completing commit.
