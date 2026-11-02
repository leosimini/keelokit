+++
id = "HARN-010"
epic = "HARN"
title = "A push of only the shared-seals branch isn't verified"
wave = 10
depends_on = ["HARN-012"]
touches = ["template/.githooks/pre-push", "template/.keelokit/bin/verify_tools.py", "template/.keelokit/bin/doctor.py", "template/docs/verify.md", "tests/test_verify_operativo.py", "tests/test_landing.py"]
dimensions = ["dx", "security"]
origin = "harbor:2026-11-02"
+++
## Context
Running Harbor against a project generated with 0.11.0: every write of Harbor's logbook (the [verify] shared_seals branch) is a push, the pre-push hook verifies every push, so each write ran a verify of the session's HEAD, and a red HEAD failed the write. The logbook holds seals, no code.

Does NOT do: trust the branch name alone. A commit with a file outside the seals' folder, or any other ref in the same push, is verified.

## User story
As Harbor writing its logbook from a session, I want that push to go through without a verify, so that a red session doesn't block recording seals, and code still never skips the gate.

## Acceptance criteria
```gherkin
Scenario: [S1] A push of only the seal branch is not verified
  Given [verify] shared_seals and a logbook commit holding only seal files
  When it alone is pushed
  Then the hook runs no verify and says why

Scenario: [S2] The seal branch with any other ref is verified
  Given the logbook and main pushed together
  When the hook runs
  Then it verifies, and main alone is verified as before

Scenario: [S3] Code on the seal branch is verified
  Given a logbook commit with a file outside the seals' folder
  When it is pushed
  Then the hook verifies

Scenario: [S4] Without the key, or with main as the seal branch, everything is verified
  Given no [verify] shared_seals, or one naming main
  When any push
  Then the hook verifies; the doctor rejects main, master and release as the seal branch
```

## Testable units
| Unit | Test type | File |
|---|---|---|
| the template's pre-push hook and verify_tools.py seal-branch-only | integration (real git push to a bare origin) | tests/test_verify_operativo.py |
| the doctor's check of the key | unit | tests/test_landing.py |

## Definition of done
`scripts/verify.sh` green, every scenario covered by a test named `test_HARN_010_S<n>_…`,
`Story:` trailer on the completing commit.
