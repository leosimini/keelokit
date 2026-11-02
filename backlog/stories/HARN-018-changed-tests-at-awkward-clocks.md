+++
id = "HARN-018"
epic = "HARN"
title = "Changed unit tests run at the clocks where date code breaks"
wave = 17
depends_on = ["HARN-017"]
touches = ["template/scripts/verify.sh", "template/.keelokit/bin/verify_tools.py", "template/.keelokit/verify-clock.toml", "copier.yml", "skills/harness-upgrade/SKILL.md", "template/docs/verify.md", "tests/test_verify_operativo.py"]
dimensions = ["dx"]
origin = "harbor:2026-11-02"
+++
## Context
Keelokit moved the clock only in --all, one year ahead, for the whole unit suite. The reds a real monorepo logged came from specific hours: late on a month's last day west of UTC, a DST change, just after midnight in another zone. Running the tests a change touches at those clocks costs seconds.

Does NOT do: integration tests under a fake clock (they need the database's clock moved too; a recipe at most).

## User story
As whoever writes a test that touches dates, I want it run at the clocks that break date code before it lands, so that a timezone or a month end doesn't turn main red later.

## Acceptance criteria
```gherkin
Scenario: [S1] A changed unit test runs at every clock
  Given a change that adds or edits Vitest and Jest unit tests
  When pnpm verify runs with faketime installed
  Then each test file runs once per scenario, with its zone and local time

Scenario: [S2] Only changed unit tests, and only with faketime
  Given a change with no unit test, an integration spec, or no faketime
  When pnpm verify runs
  Then no clock runs; without faketime a note

Scenario: [S3] The project names its own clocks
  Given a .keelokit/verify-clock.toml with its own scenarios
  When pnpm verify runs
  Then those scenarios, not the built-in ones

Scenario: [S4] A red at one clock is a red verify
  Given a test that fails at a scenario
  When pnpm verify runs
  Then the zones step is red, no seal
```

## Testable units
| Unit | Test type | File |
|---|---|---|
| verify.sh zones step and verify_tools.py clock-* | integration (fixture repo, faketime shim) | tests/test_verify_operativo.py |

## Definition of done
`scripts/verify.sh` green, every scenario covered by a test named `test_HARN_018_S<n>_…`,
`Story:` trailer on the completing commit.
