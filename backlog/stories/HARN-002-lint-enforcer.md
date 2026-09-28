+++
id = "HARN-002"
epic = "HARN"
title = "The lint enforcer check reads what a config really enables"
wave = 2
depends_on = []
touches = ["template/.keelokit/bin/doctor.py", ".keelokit/bin/doctor.py", "tests/test_doctor.py"]
dimensions = ["logic", "dx"]
invariants = []
origin = "bugbash:2026-09-27 LOG-209"
+++
## Context
The bug bash of 2026-09-27 found (LOG-209) that the doctor decides whether a `lint:` enforcer is
alive by grepping the config's text: a rule enabled through a spread preset reads as "not enabled",
and one disabled for some files reads as on. Too big for one fix: it needs the linter's own view of
the resolved config.

Does NOT do: support linters other than ESLint.

## User story
As someone whose project enables house rules through a shared preset, I want the doctor to see them
as enforced, so that I don't have to copy rules I already have.

## Acceptance criteria
```gherkin
Scenario: [S1] A preset's rule counts
  Given an ESLint config that enables a rule only through a spread preset
  When the doctor checks the rule's lint enforcer
  Then it reports the rule as enforced

Scenario: [S2] A rule turned off for part of the code is reported
  Given a config that turns the rule off for some files
  Then the doctor says which files the rule doesn't cover

Scenario: [S3] Without node the doctor says so
  Given a machine without node
  Then the doctor reports that it couldn't resolve the config, instead of guessing
```

## Testable units
| Unit | Test type | File |
|---|---|---|
| resolved-config reading | unit | tests/test_doctor.py |

## Definition of done
`scripts/verify.sh` green, every scenario covered by a test titled with its id, `Story: HARN-002`
trailer on the completing commit, addendum if the result differs.
