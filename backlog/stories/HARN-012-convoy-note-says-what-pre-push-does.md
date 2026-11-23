+++
id = "HARN-012"
epic = "HARN"
title = "The doctor's convoy note says what the pre-push hook does"
wave = 9
depends_on = ["HARN-009"]
touches = ["template/.keelokit/bin/doctor.py", "tests/test_landing.py", "template/docs/verify.md", "docs/design.md"]
dimensions = ["dx", "docs"]
origin = "harbor:2026-11-02"
+++
## Context
Under convoy the doctor said the pre-push hook protected only what reaches main. It never did: it verifies every push, a session's branch included. What a convoy project needs to hear is about the hook from before 0.11.1, which also verifies each write to Harbor's logbook (HARN-010), so a red HEAD fails the write.

Does NOT do: edit the hook (harness-upgrade does).

## User story
As someone running Harbor on a Keelokit project, I want the doctor's note to be true, so that I know when my hook needs an update and why.

## Acceptance criteria
```gherkin
Scenario: [S1] Convoy with a hook that verifies every push says so
  Given policy convoy and a pre-push hook without the shared-seals exception
  When the doctor runs
  Then a note (never a failure) says the hook verifies every push, logbook writes included, and that harness-upgrade brings the current one

Scenario: [S2] No note when the hook skips the seal branch, or there is no hook
  Given policy convoy and the current hook, or none
  When the doctor runs
  Then no landing note
```

## Testable units
| Unit | Test type | File |
|---|---|---|
| check_landing | unit (doctor on a fixture) | tests/test_landing.py |

## Definition of done
`scripts/verify.sh` green, every scenario covered by a test named `test_HARN_012_S<n>_…`,
`Story:` trailer on the completing commit.
