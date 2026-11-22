+++
id = "LEDGER-012"
epic = "LEDGER"
title = "Rule LEDGER-1, and the doctor checks that its enforcers are alive"
wave = 16
depends_on = ["LEDGER-011"]
touches = ["template/.keelokit/harness/rules.toml", ".keelokit/harness/rules.toml", "template/.keelokit/bin/doctor.py", ".keelokit/bin/doctor.py", "docs/process-rules.md", "docs/design.md", "tests/test_doctor.py", "CHANGELOG.md"]
dimensions = ["logic", "dx", "docs"]
invariants = []
origin = "docs/ledger.md — Mechanisms (LEDGER-1)"
+++
## Context
Keelokit's idea: every rule points to something that checks it, and the doctor says when a rule has lost
its check. The ledger's rule:

```toml
[[rule]]
id = "LEDGER-1"
level = "MUST"
rule = "Attribute every commit that reaches the trunk to a story (Story:, Part-of:) or a category (No-story:), and read the project's state only from ledger.py."
why = "On 2026-11-22 a coordinator reported six trains as never shipped that had been on main for weeks: the state was read from a shallow clone and from hand-kept rows."
enforced_by = ["git-hook:commit-msg", "git-hook:pre-push", "ci:checks", "script:.keelokit/bin/ledger.py"]
```

The doctor checks those enforcers are alive: `commit-msg`, `prepare-commit-msg` and `pre-push` present
and executable in `.githooks/` and `core.hooksPath` pointing there; the CI step of LEDGER-010 present; the
`ledger-snapshot` job present unless `snapshot = ""`; the corrections file valid. It prints the share of
unattributed commits since `since` and, after 14 days in a row with zero (and zero error differences)
under `warn`, recommends `enforce = "block"`. It never changes `enforce` itself. A dated exception in
`exceptions.toml` turns the rule off, as for any rule.

The CHANGELOG entry of the release that ships phase 2 has `### Upgrading from 0.15.x`: run
`harness-upgrade`, check the CI may write to the repo (workflow permissions), and leave `enforce = "warn"`
until the doctor recommends `block`.

Does NOT do: switch to block by itself.

## User story
As the person responsible for a project, I want the doctor to tell me when any piece that keeps the
ledger complete stops working, and when it is safe to block, so that I never find out from a wrong report.

## Acceptance criteria
```gherkin
Scenario: [S1] Hooks missing
  Given .githooks without commit-msg, or core.hooksPath elsewhere
  Then the doctor reports LEDGER-1 with what is missing

Scenario: [S2] The CI step missing
  Given a workflow without the ledger step
  Then the doctor reports it

Scenario: [S3] The recommendation
  Given enforce = "warn" and 14 days of trunk history with zero unattributed commits and zero errors
  Then the doctor recommends enforce = "block" and does not change it

Scenario: [S4] An exception
  Given a dated LEDGER-1 exception in exceptions.toml
  Then the doctor does not report the rule's enforcers and lists the exception until it expires

Scenario: [S5] The rule ships
  Then template/.keelokit/harness/rules.toml has LEDGER-1 with the fields above, and docs/process-rules.md lists it
```

## Testable units
| Unit | Test type | File |
|---|---|---|
| LEDGER-1's enforcers, the share, the recommendation, the exception | unit | tests/test_doctor.py |

## Definition of done
`scripts/verify.sh` green, every scenario covered by a test titled with its id, a CHANGELOG line with the
upgrade section, `Story: LEDGER-012` trailer, addendum if the result differs. Then Keelokit 0.16.0 can be
released.
