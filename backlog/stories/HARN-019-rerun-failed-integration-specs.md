+++
id = "HARN-019"
epic = "HARN"
title = "A red integration step reruns only the specs that failed and what the fix reaches"
wave = 18
depends_on = ["HARN-018"]
touches = ["template/scripts/verify.sh", "template/.keelokit/bin/verify_tools.py", "template/docs/verify.md", "tests/test_verify_operativo.py"]
dimensions = ["dx"]
origin = "harbor:2026-11-02"
+++
## Context
--rerun-failed narrowed by step, and any code fix sent it back to the normal verify, so a red integration step meant the whole suite again (half an hour in a grown monorepo). Vitest can report which spec files failed and find the specs related to a changed source.

Does NOT do: narrow anything but the API's integration specs, or narrow when the fix reaches what every spec starts from.

## User story
As whoever fixes a red integration spec, I want the rerun to cover the failed specs and what my fix reaches, so that one failing spec doesn't cost the whole suite again.

## Acceptance criteria
```gherkin
Scenario: [S1] The fix reruns the failed specs and what it reaches
  Given a red integration step with its failed specs on record, and a fix in the API's sources
  When pnpm verify --rerun-failed
  Then every other step runs, and integration only on the failed specs plus vitest related to the fix

Scenario: [S2] A spec the fix changed runs too
  Given the fix edits another integration spec
  When --rerun-failed
  Then that spec joins the failed ones

Scenario: [S3] A fix that reaches every spec runs the whole suite
  Given a fix in Prisma, the test setup, a shared package or the integration config
  When --rerun-failed
  Then the normal verify, saying why

Scenario: [S4] Without a complete record it is the whole suite
  Given no failed specs on record, or an incomplete report
  When --rerun-failed
  Then the whole suite

Scenario: [S5] A narrowed green completes the red run and seals
  Given the narrowed rerun passes on a clean tree
  When it ends
  Then the composite seal names the red run
```

## Testable units
| Unit | Test type | File |
|---|---|---|
| verify.sh integration step and verify_tools.py integration_* | integration (fixture repo, stub pnpm and docker) | tests/test_verify_operativo.py |

## Definition of done
`scripts/verify.sh` green, every scenario covered by a test named `test_HARN_019_S<n>_…`,
`Story:` trailer on the completing commit.
