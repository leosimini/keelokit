+++
id = "HARN-003"
epic = "HARN"
title = "An exception can cover only some paths, and the guard honours it"
wave = 1
depends_on = []
touches = ["template/.keelokit/bin/guard.py", ".keelokit/bin/guard.py", "template/.keelokit/bin/doctor.py", ".keelokit/bin/doctor.py", "tests/test_guard.py", "tests/test_doctor.py"]
dimensions = ["logic", "security", "dx", "integrity"]
invariants = ["INV-002"]
+++
## Context
GAP-001: the guard blocks edits to this repo's own tests of the guard and the doctor, whose
fixtures contain `it.skip`, `eslint-disable` and the like on purpose (QA-4). Decided on 2026-09-28:
allow those patterns only in the files that need them, with a registered exception — reason,
approver, expiry — that the doctor validates like any other. Any project has the same need (a lint
rule's own tests), so it goes in the template.

Does NOT do: exempt paths from SEC-1 or SEC-2 (secrets and .env stay blocked everywhere); change
what an exception without `paths` means.

## User story
As a maintainer whose tests must contain what a rule forbids, I want an exception scoped to those
files, so that the guard lets me edit them and still blocks the pattern everywhere else.

## Acceptance criteria
```gherkin
Scenario: [S1] The guard lets the pattern through only in the listed paths
  Given an active QA-4 exception with paths = ["tests/test_guard.py"]
  When an edit adds `it.skip(` to tests/test_guard.py
  Then the guard lets it through
  And the same edit to any other file is still blocked

Scenario: [S2] Only QA-4 can be scoped this way
  Given an exception with paths for SEC-1
  Then the doctor reports it as an error, and the guard ignores it

Scenario: [S3] An expired or incomplete scoped exception exempts nothing
  Given a scoped QA-4 exception that is expired, or lacks reason, approver or expiry
  Then the guard blocks the pattern in its paths too, and the doctor reports it

Scenario: [S4] A scoped exception doesn't except the whole rule
  Given only scoped QA-4 exceptions
  Then the doctor still requires QA-4's enforcers, and lists the scoped exception as a warning with its paths

Scenario: [S5] Humans' commits follow the same scope
  When a commit adds the pattern to a listed path
  Then the git pre-commit hook lets it through without keelokit.allowTamper
```
The guard still only blocks or lets a call through (INV-002).

## Testable units
| Unit | Test type | File |
|---|---|---|
| scoped allow in the Claude hook and the git hook | unit | tests/test_guard.py |
| exception validation | unit | tests/test_doctor.py |

## Definition of done
`scripts/verify.sh` green, every scenario covered by a test titled with its id, `Story: HARN-003`
trailer on the completing commit, addendum if the result differs.
