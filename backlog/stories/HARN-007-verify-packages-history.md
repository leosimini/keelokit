+++
id = "HARN-007"
epic = "HARN"
title = "Verify named packages, and record which packages a run covered"
wave = 6
depends_on = ["HARN-006"]
touches = ["template/scripts/verify.sh", "template/.keelokit/bin/verify_tools.py", "template/docs/verify.md", "tests/test_verify_operativo.py"]
dimensions = ["dx"]
origin = "harbor:2026-11-01"
+++
## Context
Harbor verifies a convoy per package set, and needs to know which packages a green step covered.

Does NOT do: per-test selection (related tests).

## User story
As whoever lands a convoy, I want `--packages` / `--filter` and the packages in the history, so that I can scope a run and judge what a green still covers.

## Acceptance criteria
```gherkin
Scenario: [S1] Packages and their dependents instead of the changed ones
  Given --packages ./packages/x,apps/web
  When verify runs
  Then pnpm gets ...{./packages/x} and ...{./apps/web}; no seal; a folder without package.json is exit 2

Scenario: [S2] A filter goes to pnpm as is and must select something
  Given --filter SELECTOR
  When it selects nothing
  Then exit 2; otherwise pnpm gets it as is

Scenario: [S3] The history says which packages a run covered
  Given any run
  When it ends
  Then packages, step_packages, the full head and the base are in its line
```

## Testable units
| Unit | Test type | File |
|---|---|---|
| verify.sh and verify_tools.py | integration (fixture repo, stub pnpm) | tests/test_verify_operativo.py |

## Definition of done
`scripts/verify.sh` green, every scenario covered by a test named `test_HARN_007_S<n>_…`,
`docs/verify.md` updated. The `Story:` trailer waits for TRACE-1 to read Python test names (it reads
only JS/TS titles under apps/, packages/ and e2e/).
